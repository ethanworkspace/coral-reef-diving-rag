from __future__ import annotations

import argparse
from pathlib import Path

from .extract import chunk, extract, sha256
from .iai import IAIClient, IAIError
from .query import answer, retrieve
from .settings import Settings
from .store import KnowledgeStore
from .structured import build_structured_database
from .cwa import DATASETS, fetch_cwa_dataset
from .observations import find_observations
from .bootstrap import bootstrap_public_data


SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".yaml", ".yml", ".json", ".csv"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ingest(args: argparse.Namespace) -> int:
    settings = Settings.from_project_root(project_root())
    store = KnowledgeStore(settings.db_path)
    root = (settings.project_root / args.root).resolve()
    # Observation tables are queried through marine_research.sqlite rather than
    # vectorized: otherwise individual species records crowd out safety evidence.
    structured_parts = {"edna", "reefcheck_taiwan_dwca", "cwa"}
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED
        and not structured_parts.intersection(path.parts)
    ]
    total = 0
    try:
        for path in files:
            parts = chunk(extract(path))
            if not parts:
                print(f"SKIP (no extractable text): {path.relative_to(settings.project_root)}")
                continue
            relative = str(path.relative_to(settings.project_root)).replace("\\", "/")
            store.replace_document(relative, sha256(path), [(part.label, part.text) for part in parts])
            total += len(parts)
            print(f"INDEXED {relative}: {len(parts)} chunks")
        if args.embed:
            client = IAIClient(settings)
            missing = store.chunks_without_embedding()
            for start in range(0, len(missing), 16):
                batch = missing[start:start + 16]
                for hit, vector in zip(batch, client.embed([item.text for item in batch])):
                    store.set_embedding(hit.chunk_id, vector)
            print(f"EMBEDDED {len(missing)} chunks using {settings.embedding_model}")
    finally:
        store.close()
    print(f"Knowledge base ready: {total} chunks rebuilt.")
    return 0


def query_command(args: argparse.Namespace) -> int:
    settings = Settings.from_project_root(project_root())
    store = KnowledgeStore(settings.db_path)
    try:
        client = IAIClient(settings) if args.llm else None
        hits = retrieve(store, args.question, client)
        print(answer(args.question, hits, client))
    except IAIError as error:
        print(f"iAI was not called successfully: {error}")
        print(answer(args.question, store.lexical_search(args.question, limit=6), None))
        return 2
    finally:
        store.close()
    return 0


def observations_command(args: argparse.Namespace) -> int:
    settings = Settings.from_project_root(project_root())
    print(
        find_observations(
            settings.project_root / "data" / "processed" / "marine_research.sqlite",
            args.latitude,
            args.longitude,
            args.radius_km,
            args.start,
            args.end,
            args.limit,
        )
    )
    return 0


def cwa_command(args: argparse.Namespace) -> int:
    try:
        return fetch_cwa_dataset(args.dataset)
    except RuntimeError as error:
        print(f"CWA data was not downloaded: {error}")
        return 2


def bootstrap_command(args: argparse.Namespace) -> int:
    return bootstrap_public_data(args.force)


def main() -> int:
    parser = argparse.ArgumentParser(description="Traceable RAG for coral-reef diving research")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest", help="extract and index local source files")
    ingest_parser.add_argument("--root", default="data/raw", help="source directory relative to the project")
    ingest_parser.add_argument("--embed", action="store_true", help="create vectors with iAI Embedding")
    ingest_parser.set_defaults(handler=ingest)
    query_parser = commands.add_parser("query", help="retrieve evidence or ask the configured RAG")
    query_parser.add_argument("question")
    query_parser.add_argument("--llm", action="store_true", help="use iAI Embedding, reranker and Furen-omni")
    query_parser.set_defaults(handler=query_command)

    structured_parser = commands.add_parser(
        "build-structured",
        help="build the local database for MPA, eDNA, and Reef Check observations",
    )
    structured_parser.set_defaults(handler=lambda args: build_structured_database())

    cwa_parser = commands.add_parser(
        "fetch-cwa",
        help="download an official CWA marine dataset with your own CWA authorization code",
    )
    cwa_parser.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    cwa_parser.set_defaults(handler=cwa_command)

    observations_parser = commands.add_parser(
        "observations",
        help="find historical eDNA and Reef Check evidence around a coordinate",
    )
    observations_parser.add_argument("--latitude", type=float, required=True)
    observations_parser.add_argument("--longitude", type=float, required=True)
    observations_parser.add_argument("--radius-km", type=float, default=5)
    observations_parser.add_argument("--start", help="optional ISO start date, e.g. 2023-01-01")
    observations_parser.add_argument("--end", help="optional ISO end date, e.g. 2024-12-31")
    observations_parser.add_argument("--limit", type=int, default=20)
    observations_parser.set_defaults(handler=observations_command)

    bootstrap_parser = commands.add_parser(
        "bootstrap-public",
        help="download the public MPA/eDNA core data and rebuild the structured database",
    )
    bootstrap_parser.add_argument("--force", action="store_true", help="re-download existing public core files")
    bootstrap_parser.set_defaults(handler=bootstrap_command)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
