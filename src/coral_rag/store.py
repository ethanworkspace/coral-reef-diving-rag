from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path


class FTSUnavailableError(RuntimeError):
    """The Python SQLite build does not include the required FTS5 module."""


class FTSIndexNotReadyError(RuntimeError):
    """The FTS table is absent or does not match the current chunks."""


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    path: str
    ordinal: int
    label: str
    text: str
    score: float
    embedding: list[float] | None

    @property
    def document_reference(self) -> str:
        """Stable, non-path identifier suitable for public retrieval responses."""
        digest = hashlib.sha256(self.path.encode("utf-8")).hexdigest()[:16]
        return f"doc-{digest}"

    @property
    def chunk_reference(self) -> str:
        return f"{self.document_reference}-chunk-{self.ordinal + 1}"


def normalized_fts_terms(text: str) -> list[str]:
    """Return deterministic CJK bigrams plus normalized Latin/number terms.

    FTS5's built-in unicode61 tokenizer preserves a contiguous CJK run as one
    token. Indexing overlapping bigrams provides a small, offline-compatible
    alternative without pretending that a language-specific segmenter exists.
    """
    normalized = unicodedata.normalize("NFKC", text).lower()
    latin = re.findall(r"[a-z0-9]{2,}", normalized)
    cjk_runs = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", normalized)
    cjk_terms: list[str] = []
    for run in cjk_runs:
        cjk_terms.extend(run[index:index + 2] for index in range(len(run) - 1))
        if len(run) == 1:
            cjk_terms.append(run)
    return list(dict.fromkeys([*latin, *cjk_terms]))[:80]


def normalized_cjk_character_terms(text: str) -> list[str]:
    """Return a conservative CJK-character fallback for wording-order variants."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return list(dict.fromkeys(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", normalized)))[:20]


class KnowledgeStore:
    def __init__(self, db_path: Path, *, initialize: bool = True) -> None:
        if initialize:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(db_path)
        else:
            self.connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if initialize:
            self._init_schema()

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                label TEXT NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, ordinal);
            """
        )
        self._create_fts_table("chunks_fts")

    def _create_fts_table(self, table_name: str) -> None:
        try:
            self.connection.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5("
                "chunk_id UNINDEXED, search_text, tokenize='unicode61 remove_diacritics 2')"
            )
        except sqlite3.OperationalError as error:
            if "fts5" in str(error).lower() or "module" in str(error).lower():
                raise FTSUnavailableError("SQLite FTS5 is unavailable in this Python environment") from error
            raise

    def replace_document(self, path: str, checksum: str, chunks: list[tuple[str, str]]) -> int:
        with self.connection:
            self.connection.execute("DELETE FROM documents WHERE path = ?", (path,))
            cursor = self.connection.execute(
                "INSERT INTO documents(path, checksum) VALUES (?, ?)", (path, checksum)
            )
            document_id = int(cursor.lastrowid)
            self.connection.executemany(
                "INSERT INTO chunks(document_id, ordinal, label, text) VALUES (?, ?, ?, ?)",
                [(document_id, ordinal, label, text) for ordinal, (label, text) in enumerate(chunks)],
            )
        return document_id

    def rebuild_fts(self) -> int:
        """Atomically replace the FTS table from current chunks."""
        try:
            with self.connection:
                self.connection.execute("DROP TABLE IF EXISTS chunks_fts_next")
                self._create_fts_table("chunks_fts_next")
                rows = self.connection.execute("SELECT id, label, text FROM chunks ORDER BY id").fetchall()
                self.connection.executemany(
                    "INSERT INTO chunks_fts_next(chunk_id, search_text) VALUES (?, ?)",
                    [
                        (
                            str(row["id"]),
                            " ".join(normalized_fts_terms(f"{row['label']}\n{row['text']}") + normalized_cjk_character_terms(f"{row['label']}\n{row['text']}")),
                        )
                        for row in rows
                    ],
                )
                self.connection.execute("DROP TABLE IF EXISTS chunks_fts")
                self.connection.execute("ALTER TABLE chunks_fts_next RENAME TO chunks_fts")
        except FTSUnavailableError:
            raise
        except (sqlite3.Error, UnicodeError, ValueError) as error:
            raise FTSIndexNotReadyError("FTS index rebuild failed") from error
        return len(rows)

    def fts_diagnostics(self) -> dict[str, int | bool]:
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
        ).fetchone()
        if not table:
            return {"available": False, "chunk_count": 0, "indexed_count": 0, "current": False}
        chunk_count = int(self.connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        indexed_count = int(self.connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0])
        missing_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM chunks c LEFT JOIN chunks_fts f "
                "ON f.chunk_id = CAST(c.id AS TEXT) WHERE f.chunk_id IS NULL"
            ).fetchone()[0]
        )
        return {
            "available": True,
            "chunk_count": chunk_count,
            "indexed_count": indexed_count,
            "current": chunk_count == indexed_count and missing_count == 0,
        }

    def set_embedding(self, chunk_id: int, embedding: list[float]) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE chunks SET embedding = ? WHERE id = ?", (json.dumps(embedding), chunk_id)
            )

    def chunks_without_embedding(self) -> list[SearchHit]:
        return self._select("WHERE c.embedding IS NULL")

    def all_chunks(self) -> list[SearchHit]:
        return self._select("")

    def _select(self, where: str, parameters: tuple[str, ...] = ()) -> list[SearchHit]:
        rows = self.connection.execute(
            f"""
            SELECT c.id, d.path, c.ordinal, c.label, c.text, c.embedding
            FROM chunks c JOIN documents d ON d.id = c.document_id {where}
            """,
            parameters,
        ).fetchall()
        return [
            SearchHit(
                chunk_id=row["id"], path=row["path"], ordinal=row["ordinal"], label=row["label"],
                text=row["text"], score=0.0,
                embedding=json.loads(row["embedding"]) if row["embedding"] else None,
            )
            for row in rows
        ]

    def fts_search(self, query: str, limit: int = 16) -> tuple[list[SearchHit], list[str]]:
        """Search current FTS5 data without exposing FTS query syntax to users."""
        terms = normalized_fts_terms(query)
        if not terms:
            return [], []
        if not self.fts_diagnostics().get("current"):
            raise FTSIndexNotReadyError("FTS index is not built for the current document chunks")
        expression = " AND ".join(f'"{term}"' for term in terms)
        try:
            def query_rows(match_expression: str, *, curated_only: bool = False) -> list[sqlite3.Row]:
                where = "WHERE chunks_fts MATCH ?"
                parameters: list[object] = [match_expression]
                if curated_only:
                    where += " AND d.path GLOB 'curated_public_knowledge/*'"
                parameters.append(limit)
                return self.connection.execute(
                f"""
                SELECT c.id, d.path, c.ordinal, c.label, c.text, c.embedding,
                       bm25(chunks_fts) AS rank
                FROM chunks_fts
                JOIN chunks c ON c.id = CAST(chunks_fts.chunk_id AS INTEGER)
                JOIN documents d ON d.id = c.document_id
                {where}
                ORDER BY rank, c.id
                LIMIT ?
                """,
                    parameters,
                ).fetchall()

            rows = query_rows(expression)
            fallback_terms = normalized_cjk_character_terms(query)
            if not rows and len(fallback_terms) >= 2:
                terms = fallback_terms
                # A short CJK wording-order variant can have no shared bigram
                # with its source text (for example, equivalent reordered
                # characters). Use a bounded recall fallback only after the
                # precise AND query has no result.
                rows = query_rows(" OR ".join(f'"{term}"' for term in terms), curated_only=True)
        except sqlite3.OperationalError as error:
            raise FTSIndexNotReadyError("FTS search could not run") from error
        return [
            SearchHit(
                chunk_id=row["id"], path=row["path"], ordinal=row["ordinal"], label=row["label"],
                text=row["text"], score=float(-row["rank"]),
                embedding=json.loads(row["embedding"]) if row["embedding"] else None,
            )
            for row in rows
        ], terms

    def lexical_search(self, query: str, limit: int = 16) -> list[SearchHit]:
        """Legacy LIKE fallback; it is intentionally not used by the FTS API."""
        terms = self._terms(query)
        if not terms:
            return []
        values = [f"%{term}%" for term in terms]
        clause = " OR ".join("c.text LIKE ?" for _ in values)
        hits = self._select(f"WHERE {clause}", tuple(values))
        scored: list[SearchHit] = []
        for hit in hits:
            normalized = hit.text.lower()
            score = sum(normalized.count(term.lower()) * max(1, len(term)) for term in terms)
            if score:
                scored.append(SearchHit(**{**hit.__dict__, "score": float(score)}))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

    @staticmethod
    def _terms(query: str) -> list[str]:
        latin = re.findall(r"[A-Za-z0-9_-]{2,}", query)
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", query))
        bigrams = [cjk[index:index + 2] for index in range(max(0, len(cjk) - 1))]
        return list(dict.fromkeys(latin + bigrams))[:30]
