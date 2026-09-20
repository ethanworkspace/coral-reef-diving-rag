from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from .full_text import search_with_policy
from .iai import IAIClient, IAIError
from .query import answer, retrieve
from .settings import Settings
from .store import KnowledgeStore
from .structured import build_structured_database
from .cwa import DATASETS, fetch_cwa_dataset
from .observations import find_observations
from .bootstrap import bootstrap_public_data
from .candidate_audit import generate_dive_site_candidate_audit
from .iai_chat_pilot import evaluate_iai_chat_pilot, evaluate_iai_research_pilot
from .iai_diagnostics import diagnose_iai_connectivity
from .iai_chat_probe import probe_iai_chat_protocol
from .cwa_tls import diagnose_cwa_tls
from .raw_data_recovery import (
    EXIT_MANIFEST_INVALID,
    inventory_rows,
    verify_raw_data,
)


SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".yaml", ".yml", ".json", ".csv"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ingest(args: argparse.Namespace) -> int:
    # Keep unrelated document-extraction dependencies out of build-structured.
    from .extract import chunk, extract, sha256
    from .knowledge import curated_public_knowledge_documents

    root_project = project_root()
    root = (root_project / args.root).resolve()
    rag_db = getattr(args, "rag_db", None)
    target_database = Path(rag_db).resolve() if rag_db else root_project / "data" / "processed" / "rag.sqlite"
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
    staging_path = target_database.with_name(f"{target_database.name}.staging-{uuid4().hex}")
    total = 0
    try:
        store = KnowledgeStore(staging_path)
        try:
            for path in files:
                parts = chunk(extract(path))
                if not parts:
                    print(f"SKIP (no extractable text): {path.relative_to(root_project)}")
                    continue
                relative = str(path.relative_to(root_project)).replace("\\", "/")
                store.replace_document(relative, sha256(path), [(part.label, part.text) for part in parts])
                total += len(parts)
                print(f"INDEXED {relative}: {len(parts)} chunks")
            for document in curated_public_knowledge_documents(root_project):
                store.replace_document(
                    document["path"], document["checksum"], [(document["label"], document["text"])],
                )
                total += 1
                print(f"INDEXED curated public knowledge: {document['content_id']}: 1 chunks")
            if args.embed:
                settings = Settings.from_project_root(root_project)
                client = IAIClient(settings)
                missing = store.chunks_without_embedding()
                for start in range(0, len(missing), 16):
                    batch = missing[start:start + 16]
                    for hit, vector in zip(batch, client.embed([item.text for item in batch])):
                        store.set_embedding(hit.chunk_id, vector)
                print(f"EMBEDDED {len(missing)} chunks using {settings.embedding_model}")
            indexed = store.rebuild_fts()
        finally:
            store.close()
        os.replace(staging_path, target_database)
    except OSError as error:
        staging_path.unlink(missing_ok=True)
        raise RuntimeError("knowledge index replacement failed; prior index was preserved") from error
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise
    print(f"Knowledge base ready: {total} chunks rebuilt; FTS5 indexed {indexed} chunks.")
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


def search_command(args: argparse.Namespace) -> int:
    """Run only source-governed FTS retrieval; never contact iAI or generate prose."""
    root = project_root()
    configured = os.getenv("CORAL_RAG_RAG_DB")
    database = Path(configured).resolve() if configured else root / "data" / "processed" / "rag.sqlite"
    if not database.exists():
        print(json.dumps({"error": "fts_index_unavailable", "detail": "Run ingest to build the FTS5 index."}, ensure_ascii=False))
        return 2
    store = KnowledgeStore(database, initialize=False)
    try:
        payload = search_with_policy(
            store, root, args.query, limit=args.limit,
            include_restricted=args.include_restricted,
        )
    except (RuntimeError, sqlite3.Error) as error:
        print(json.dumps({"error": "fts_index_unavailable", "detail": str(error)}, ensure_ascii=False))
        return 2
    finally:
        store.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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


def diagnose_cwa_tls_command(args: argparse.Namespace) -> int:
    """Run the opt-in, one-handshake CWA TLS diagnostic without an API request."""
    result = diagnose_cwa_tls(project_root(), confirm_network_cwa=args.confirm_network_cwa)
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "tls_verified" else 2


def bootstrap_command(args: argparse.Namespace) -> int:
    return bootstrap_public_data(args.force)


def audit_dive_site_candidates_command(args: argparse.Namespace) -> int:
    root = project_root()
    result = generate_dive_site_candidate_audit(
        root / "data" / "processed" / "marine_research.sqlite",
        root / args.output,
        root / "metadata" / "raw_file_manifest.tsv",
    )
    print("Dive-site candidate audit ready:", result)
    return 0


def evaluate_iai_chat_pilot_command(args: argparse.Namespace) -> int:
    result = evaluate_iai_chat_pilot(project_root(), confirm_live_iai=args.confirm_live_iai)
    print(json.dumps({"status": result["status"], "actual_calls": result["actual_calls"]}, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 2


def evaluate_iai_research_pilot_command(args: argparse.Namespace) -> int:
    result = evaluate_iai_research_pilot(project_root(), confirm_live_iai=args.confirm_live_iai)
    print(json.dumps({"status": result["status"], "actual_calls": result["actual_calls"]}, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 2


def diagnose_iai_command(args: argparse.Namespace) -> int:
    """Run the deliberately limited non-completion iAI diagnostics command."""
    result = diagnose_iai_connectivity(project_root(), confirm_network_iai=args.confirm_network_iai)
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "models_discovery_success" else 2


def probe_iai_chat_command(args: argparse.Namespace) -> int:
    """Perform the sole explicitly confirmed, data-minimized chat protocol probe."""
    result = probe_iai_chat_protocol(project_root(), confirm_live_iai=args.confirm_live_iai)
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "chat_protocol_success" else 2


def verify_raw_data_command(args: argparse.Namespace) -> int:
    """Read-only raw-input verification; no download, repair, or database activity."""
    if not args.check_only:
        print(json.dumps({"status": "check_only_flag_required"}, ensure_ascii=False))
        return 2
    try:
        exit_code, checks = verify_raw_data(project_root())
    except ValueError:
        print(json.dumps({"status": "manifest_invalid"}, ensure_ascii=False))
        return EXIT_MANIFEST_INVALID
    rows = inventory_rows(project_root())
    summary = {
        "status": {0: "complete", 2: "missing_required", 3: "hash_mismatch"}.get(exit_code, "manifest_invalid"),
        "datasets": len(rows),
        "present": sum(check.exists for check in checks),
        "missing": sum(not check.exists for check in checks),
        "hash_mismatch": sum(check.hash_status == "mismatch" for check in checks),
        "required_missing": sum(not check.exists and check.required_for in {"structured", "fts", "structured_and_fts"} for check in checks),
        "by_recovery_type": {kind: sum(check.recovery_type == kind for check in checks) for kind in sorted({check.recovery_type for check in checks})},
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return exit_code


def build_structured_command(args: argparse.Namespace) -> int:
    target = Path(args.structured_db).resolve() if args.structured_db else None
    return build_structured_database(project_root(), target_path=target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Traceable RAG for coral-reef diving research")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest", help="extract and index local source files")
    ingest_parser.add_argument("--root", default="data/raw", help="source directory relative to the project")
    ingest_parser.add_argument("--rag-db", help="optional isolated RAG SQLite output path; default keeps existing behavior")
    ingest_parser.add_argument("--embed", action="store_true", help="create vectors with iAI Embedding")
    ingest_parser.set_defaults(handler=ingest)
    query_parser = commands.add_parser("query", help="retrieve evidence or ask the configured RAG")
    query_parser.add_argument("question")
    query_parser.add_argument("--llm", action="store_true", help="use explicitly configured local iAI models")
    query_parser.set_defaults(handler=query_command)
    research_pilot_parser = commands.add_parser(
        "evaluate-iai-research-pilot",
        help="explicit opt-in 12-call research-only iAI pilot; no chat API or persistence",
    )
    research_pilot_parser.add_argument("--confirm-live-iai", action="store_true")
    research_pilot_parser.set_defaults(handler=evaluate_iai_research_pilot_command)
    iai_diagnostic_parser = commands.add_parser(
        "diagnose-iai",
        help="explicit one-request iAI models-discovery diagnostic; never generates a chat completion",
    )
    iai_diagnostic_parser.add_argument(
        "--confirm-network-iai", action="store_true",
        help="allow at most one HTTPS models-discovery request using existing local iAI settings",
    )
    iai_diagnostic_parser.set_defaults(handler=diagnose_iai_command)
    iai_chat_probe_parser = commands.add_parser(
        "probe-iai-chat",
        help="explicit one-request fixed JSON chat protocol probe; never sends project or user data",
    )
    iai_chat_probe_parser.add_argument(
        "--confirm-live-iai", action="store_true",
        help="allow exactly one fixed, non-streaming chat completion protocol request",
    )
    iai_chat_probe_parser.set_defaults(handler=probe_iai_chat_command)
    search_parser = commands.add_parser("search", help="FTS5 retrieval with source-status controls; never calls an LLM")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10, choices=range(1, 21))
    search_parser.add_argument(
        "--include-restricted", action="store_true",
        help="research-only: include pending, excluded, and untracked source metadata without excerpts",
    )
    search_parser.set_defaults(handler=search_command)

    structured_parser = commands.add_parser(
        "build-structured",
        help="build the local database for curated sites, MPA, eDNA, Reef Check, authorized tide forecasts, and approved CWA general weather snapshots",
    )
    structured_parser.add_argument("--structured-db", help="optional isolated structured SQLite output path; default keeps existing behavior")
    structured_parser.set_defaults(handler=build_structured_command)

    candidate_audit_parser = commands.add_parser(
        "audit-dive-site-candidates",
        help="create a review-only, traceable inventory of ecological location evidence",
    )
    candidate_audit_parser.add_argument(
        "--output", default="metadata/dive_site_candidate_audit.csv",
        help="CSV output path relative to the project root",
    )
    candidate_audit_parser.set_defaults(handler=audit_dive_site_candidates_command)

    iai_pilot_parser = commands.add_parser(
        "evaluate-iai-chat-pilot",
        help="explicitly opt in to a bounded local iAI chat-candidate pilot; no chat API is created",
    )
    iai_pilot_parser.add_argument("--confirm-live-iai", action="store_true", help="allow at most 24 sequential iAI requests")
    iai_pilot_parser.set_defaults(handler=evaluate_iai_chat_pilot_command)

    raw_verify_parser = commands.add_parser(
        "verify-raw-data",
        help="read only the manifest-listed local raw inputs; never download, repair, or rebuild",
    )
    raw_verify_parser.add_argument("--check-only", action="store_true", help="required acknowledgement that this command is read-only")
    raw_verify_parser.set_defaults(handler=verify_raw_data_command)

    cwa_parser = commands.add_parser(
        "fetch-cwa",
        help="download an approved official CWA dataset with your own CWA authorization code",
    )
    cwa_parser.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    cwa_parser.set_defaults(handler=cwa_command)

    cwa_tls_parser = commands.add_parser(
        "diagnose-cwa-tls",
        help="explicit one-handshake CWA TLS diagnostic; never downloads a dataset",
    )
    cwa_tls_parser.add_argument(
        "--confirm-network-cwa", action="store_true",
        help="allow at most one TLS handshake with the fixed official CWA HTTPS host",
    )
    cwa_tls_parser.set_defaults(handler=diagnose_cwa_tls_command)

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
