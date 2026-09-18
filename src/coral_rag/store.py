from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    path: str
    label: str
    text: str
    score: float
    embedding: list[float] | None


class KnowledgeStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
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
            SELECT c.id, d.path, c.label, c.text, c.embedding
            FROM chunks c JOIN documents d ON d.id = c.document_id {where}
            """
        , parameters).fetchall()
        return [
            SearchHit(
                chunk_id=row["id"], path=row["path"], label=row["label"], text=row["text"],
                score=0.0, embedding=json.loads(row["embedding"]) if row["embedding"] else None,
            )
            for row in rows
        ]

    def lexical_search(self, query: str, limit: int = 16) -> list[SearchHit]:
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
