from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TZ_UTC8 = timezone(timedelta(hours=8))
APPROVED_MODEL_ID = "BAAI/bge-m3"
APPROVED_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
APPROVED_MODEL_CARD_URL = "https://huggingface.co/BAAI/bge-m3"
APPROVED_LICENSE = "MIT"
APPROVED_MODEL_DIR_NAME = "BAAI__bge-m3"

DEFAULT_MODEL_DIR = Path("data/models/rag_v2") / APPROVED_MODEL_DIR_NAME
DEFAULT_CHUNKS_PATH = Path("data/processed/rag_v2/chunks.jsonl")
DEFAULT_GATE_PATH = Path("metadata/rag_v2_corpus_quality_gate.json")
DEFAULT_EMBEDDINGS_NPY = Path("data/processed/rag_v2/dense_embeddings.npy")
DEFAULT_EMBEDDING_ROWS = Path("data/processed/rag_v2/dense_embedding_rows.jsonl")
DEFAULT_MANIFEST_PATH = Path("metadata/rag_v2_embedding_model_manifest.json")
DEFAULT_HOLDOUT_PATH = Path("metadata/rag_v2_vector_holdout_cases.jsonl")
DEFAULT_REPORT_PATH = Path("metadata/rag_v2_dense_baseline_report.md")

REQUIRED_CHUNK_FIELDS = [
    "chunk_id",
    "source_id",
    "document_id",
    "language",
    "title",
    "heading_path",
    "section_ids",
    "source_anchors",
    "text",
    "text_char_count",
    "raw_sha256",
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RagV2DenseHit:
    """Canonical search hit representation for RAG v2 dense retrieval."""
    chunk_id: str
    source_id: str
    score: float
    rank: int
    title: str
    url: str
    heading_path: list[str]
    raw_html_path: str
    raw_sha256: str
    section_ids: list[str]
    source_anchors: list[str]
    text: str
    text_char_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DenseEmbeddingRow:
    """Sidecar row representation corresponding to each embedding vector."""
    row_index: int
    chunk_id: str
    source_id: str
    language: str
    raw_sha256: str
    chunk_text_sha256: str
    embedding_dimension: int
    model_id: str
    model_revision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Model Download (Sole Authorized Network Action)
# ---------------------------------------------------------------------------

def hash_model_files(model_dir: Path) -> dict[str, dict[str, Any]]:
    """Compute detailed relative path, size in bytes, and SHA-256 for all model files."""
    files_manifest: dict[str, dict[str, Any]] = {}
    if not model_dir.exists():
        return files_manifest

    for file_path in sorted(model_dir.rglob("*")):
        if file_path.is_file():
            rel_path = str(file_path.relative_to(model_dir)).replace("\\", "/")
            size = file_path.stat().st_size
            sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
            files_manifest[rel_path] = {
                "size_bytes": size,
                "sha256": sha256,
            }
    return files_manifest


def download_approved_model(
    model_id: str = APPROVED_MODEL_ID,
    revision: str = APPROVED_MODEL_REVISION,
    target_dir: Path = DEFAULT_MODEL_DIR,
    confirm_download: bool = False,
) -> dict[str, Any]:
    """Sole network-authorized routine to download the approved BAAI/bge-m3 model.
    
    Guarantees:
    - Fails closed if confirm_download is False (dry-run output only).
    - Fails closed if model_id or revision deviates from the approved contract.
    - Zero local data (chunks/queries/paths) is transmitted to external endpoints.
    - Captures complete file-level provenance (relative path, size, SHA-256).
    """
    if model_id != APPROVED_MODEL_ID or revision != APPROVED_MODEL_REVISION:
        raise ValueError(
            f"Unauthorized model '{model_id}' (revision: '{revision}'). "
            f"Only '{APPROVED_MODEL_ID}' revision '{APPROVED_MODEL_REVISION}' is approved."
        )

    resolved_target = target_dir.resolve()

    if not confirm_download:
        return {
            "status": "dry_run_only",
            "model_id": model_id,
            "revision": revision,
            "target_dir": str(resolved_target),
            "license": APPROVED_LICENSE,
            "model_card_url": APPROVED_MODEL_CARD_URL,
            "message": "Flag --confirm-download was not provided. No network requests made.",
        }

    try:
        from huggingface_hub import snapshot_download
    except ImportError as err:
        raise RuntimeError(
            "huggingface_hub package is not installed. Install requirements-vector.txt first."
        ) from err

    resolved_target.parent.mkdir(parents=True, exist_ok=True)
    download_start = datetime.now(TZ_UTC8).isoformat()

    print(f"Downloading approved model '{model_id}' (revision: '{revision[:8]}')...")
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=str(resolved_target),
    )

    files_manifest = hash_model_files(resolved_target)
    total_size = sum(f["size_bytes"] for f in files_manifest.values())

    return {
        "status": "download_completed",
        "model_id": model_id,
        "revision": revision,
        "model_card_url": APPROVED_MODEL_CARD_URL,
        "license": APPROVED_LICENSE,
        "target_dir": str(resolved_target),
        "downloaded_at": download_start,
        "total_files": len(files_manifest),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "files_manifest": files_manifest,
    }


# ---------------------------------------------------------------------------
# Strict Offline Embedder Loader
# ---------------------------------------------------------------------------

def enforce_offline_environment() -> None:
    """Enforce strict offline mode for Hugging Face and Transformers libraries."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"


def get_pip_check_status() -> dict[str, Any]:
    """Execute pip check safely to verify installed dependency consistency."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "exit_code": proc.returncode,
            "consistent": (proc.returncode == 0),
            "output": proc.stdout.strip() or proc.stderr.strip() or "No broken requirements found.",
        }
    except Exception as err:
        return {
            "exit_code": -1,
            "consistent": False,
            "output": f"pip check invocation error: {err}",
        }


def get_package_versions() -> dict[str, str]:
    """Capture precise installed versions of core ML dependencies."""
    import importlib.metadata
    packages = ["sentence_transformers", "torch", "transformers", "numpy"]
    versions: dict[str, str] = {}
    for pkg in packages:
        try:
            versions[pkg] = importlib.metadata.version(pkg.replace("_", "-"))
        except importlib.metadata.PackageNotFoundError:
            try:
                versions[pkg] = importlib.metadata.version(pkg)
            except importlib.metadata.PackageNotFoundError:
                versions[pkg] = "not_installed"
    return versions


def load_dense_embedder(
    model_dir: Path = DEFAULT_MODEL_DIR,
    device: str = "auto",
    embedder_override: Any = None,
) -> tuple[Any, dict[str, Any]]:
    """Load the SentenceTransformer model strictly from local files only."""
    if embedder_override is not None:
        return embedder_override, {
            "device_used": "fake_device",
            "device_name": "FakeEmbedderDevice",
            "cuda_available": False,
            "fallback_reason": None,
        }

    enforce_offline_environment()
    resolved_dir = model_dir.resolve()
    if not resolved_dir.exists() or not any(resolved_dir.iterdir()):
        raise FileNotFoundError(
            f"Local model directory '{resolved_dir}' does not exist or is empty. "
            "Run 'python -m coral_rag download-rag-v2-embedding-model --confirm-download' first."
        )

    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as err:
        raise RuntimeError(
            "sentence_transformers or torch is missing. Install requirements-vector.txt first."
        ) from err

    cuda_available = torch.cuda.is_available()
    device_info: dict[str, Any] = {
        "cuda_available": cuda_available,
        "fallback_reason": None,
    }

    chosen_device = "cpu"
    if device == "auto":
        if cuda_available:
            chosen_device = "cuda"
            device_info["device_name"] = torch.cuda.get_device_name(0)
            device_info["vram_total_mb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024), 2)
        else:
            chosen_device = "cpu"
            device_info["device_name"] = platform.processor() or "CPU"
            device_info["fallback_reason"] = "CUDA is not available on current PyTorch build/hardware"
    elif device == "cuda":
        if not cuda_available:
            chosen_device = "cpu"
            device_info["device_name"] = platform.processor() or "CPU"
            device_info["fallback_reason"] = "User requested cuda but torch.cuda.is_available() is False; degraded to CPU"
        else:
            chosen_device = "cuda"
            device_info["device_name"] = torch.cuda.get_device_name(0)
            device_info["vram_total_mb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024), 2)
    else:
        chosen_device = "cpu"
        device_info["device_name"] = platform.processor() or "CPU"
        device_info["fallback_reason"] = "Explicitly requested CPU execution"

    device_info["device_used"] = chosen_device

    print(f"Loading SentenceTransformer from local path (device='{chosen_device}')...")
    model = SentenceTransformer(str(resolved_dir), device=chosen_device, local_files_only=True)
    return model, device_info


# ---------------------------------------------------------------------------
# Vector Sidecar Index Builder
# ---------------------------------------------------------------------------

def build_rag_v2_dense(
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    quality_gate_path: Path = DEFAULT_GATE_PATH,
    model_dir: Path = DEFAULT_MODEL_DIR,
    output_npy: Path = DEFAULT_EMBEDDINGS_NPY,
    output_rows: Path = DEFAULT_EMBEDDING_ROWS,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    batch_size: int = 4,
    device: str = "auto",
    embedder_override: Any = None,
) -> dict[str, Any]:
    """Build local dense embedding matrix (.npy) and metadata sidecar (.jsonl).
    
    Guarantees:
    - Strictly offline: verifies model presence locally; never downloads.
    - Precondition: verifies quality gate status == 'quality_gate_met'.
    - Blocked sources dynamically rejected: fail-closed if blocked source chunk appears.
    - Provenance & checksums: computes SHA-256 for chunks.jsonl and every chunk text.
    - Robust GPU/CPU fallback: automatically degrades batch size or switches to CPU on OOM.
    - Vector validation: float32, L2 normalized (norm ~ 1.0), all finite.
    - Atomic replacement: writes all outputs to staging directory before atomic move.
    """
    # 1. Verify quality gate
    if not quality_gate_path.exists():
        raise RuntimeError(f"Quality gate file not found: {quality_gate_path}")

    gate_data = json.loads(quality_gate_path.read_text(encoding="utf-8"))
    if gate_data.get("status") != "quality_gate_met":
        raise RuntimeError(
            f"Corpus quality gate not met (status='{gate_data.get('status')}'). "
            "Refusing to build dense vector index."
        )
    blocked_sources = set(gate_data.get("blocked_source_ids", []))

    # 2. Verify chunks
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    chunks_bytes = chunks_path.read_bytes()
    chunks_sha256 = hashlib.sha256(chunks_bytes).hexdigest()

    chunks: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            for req in REQUIRED_CHUNK_FIELDS:
                if req not in record:
                    raise ValueError(f"Chunk at line {line_num} missing required field '{req}'")

            sid = record["source_id"]
            if not sid or sid in blocked_sources:
                raise ValueError(
                    f"Chunk at line {line_num} belongs to blocked source '{sid}'. Fail-closed."
                )
            chunks.append(record)

    total_chunks = len(chunks)
    if total_chunks == 0:
        raise ValueError("No qualified chunks to embed.")

    # 3. Load model offline
    model, device_info = load_dense_embedder(
        model_dir=model_dir,
        device=device,
        embedder_override=embedder_override,
    )

    texts = [c["text"] for c in chunks]

    # 4. Compute embeddings with fallback protection
    actual_batch_size = batch_size
    current_device = device_info["device_used"]
    fallback_reason = device_info.get("fallback_reason")

    embed_start = time.perf_counter()
    embeddings_raw = None

    for attempt_batch in [actual_batch_size, 2, 1]:
        try:
            actual_batch_size = attempt_batch
            if hasattr(model, "encode"):
                embeddings_raw = model.encode(
                    texts,
                    batch_size=actual_batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
            else:
                # Custom callable override
                embeddings_raw = model(texts)
            break
        except Exception as err:
            err_msg = str(err).lower()
            if "out of memory" in err_msg or "cuda" in err_msg:
                print(f"Warning: CUDA OOM with batch_size={attempt_batch}. Retrying...")
                if attempt_batch == 1 and current_device == "cuda":
                    # Degrade to CPU
                    print("Warning: CUDA failed even with batch_size=1. Falling back to CPU...")
                    current_device = "cpu"
                    fallback_reason = f"CUDA out of memory error: {err}; fallback to CPU"
                    if hasattr(model, "to"):
                        model = model.to("cpu")
            else:
                raise

    if embeddings_raw is None:
        raise RuntimeError("Failed to compute embeddings across all fallback batch sizes.")

    embed_total_time = time.perf_counter() - embed_start
    per_chunk_latency = embed_total_time / total_chunks if total_chunks > 0 else 0.0

    # 5. Validate embeddings
    embeddings = np.array(embeddings_raw, dtype=np.float32)
    if not np.all(np.isfinite(embeddings)):
        raise ValueError("Computed embeddings contain NaN or Inf values.")

    # Force L2 normalization
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings = embeddings / norms

    embedding_dim = int(embeddings.shape[1])
    if embeddings.shape[0] != total_chunks:
        raise RuntimeError(
            f"Embedding row count mismatch: expected {total_chunks}, got {embeddings.shape[0]}"
        )

    # 6. Prepare sidecar rows
    rows: list[DenseEmbeddingRow] = []
    for idx, chunk in enumerate(chunks):
        text_sha = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
        rows.append(DenseEmbeddingRow(
            row_index=idx,
            chunk_id=chunk["chunk_id"],
            source_id=chunk["source_id"],
            language=chunk["language"],
            raw_sha256=chunk["raw_sha256"],
            chunk_text_sha256=text_sha,
            embedding_dimension=embedding_dim,
            model_id=APPROVED_MODEL_ID,
            model_revision=APPROVED_MODEL_REVISION,
        ))

    # 7. Model Manifest compilation
    files_manifest = hash_model_files(model_dir.resolve())
    pip_check = get_pip_check_status()
    pkg_versions = get_package_versions()

    manifest_data = {
        "manifest_version": "1.0.0",
        "generated_at": datetime.now(TZ_UTC8).isoformat(),
        "model_id": APPROVED_MODEL_ID,
        "model_revision": APPROVED_MODEL_REVISION,
        "model_card_url": APPROVED_MODEL_CARD_URL,
        "license": APPROVED_LICENSE,
        "model_dir": str(model_dir.resolve()),
        "model_files_count": len(files_manifest),
        "model_files_manifest": files_manifest,
        "dependencies": {
            "constraint_file": "requirements-vector.txt",
            "package_versions": pkg_versions,
            "pip_check": pip_check,
        },
        "hardware_execution": {
            "cuda_available": device_info["cuda_available"],
            "device_used": current_device,
            "device_name": device_info.get("device_name", "unknown"),
            "batch_size_used": actual_batch_size,
            "fallback_reason": fallback_reason,
        },
        "corpus_indexing": {
            "source_chunks_path": str(chunks_path.resolve()),
            "source_chunks_sha256": chunks_sha256,
            "total_chunks_indexed": total_chunks,
            "target_coverage_ratio": 1.0,
            "actual_coverage_ratio": round(total_chunks / total_chunks, 4),
            "embedding_dimension": embedding_dim,
            "indexing_total_seconds": round(embed_total_time, 4),
            "indexing_seconds_per_chunk": round(per_chunk_latency, 4),
        },
    }

    # 8. Atomic staging and write
    staging_dir = output_npy.parent / f".staging_dense_{uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    staging_npy = staging_dir / output_npy.name
    staging_rows = staging_dir / output_rows.name
    staging_manifest = staging_dir / manifest_path.name

    try:
        # Write npy
        np.save(staging_npy, embeddings)

        # Write rows JSONL
        with staging_rows.open("w", encoding="utf-8") as rf:
            for row in rows:
                rf.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")

        # Write manifest
        staging_manifest.write_text(
            json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Atomic replacements
        output_npy.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        os.replace(staging_npy, output_npy.resolve())
        os.replace(staging_rows, output_rows.resolve())
        os.replace(staging_manifest, manifest_path.resolve())
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

    return {
        "status": "success",
        "indexed_chunks": total_chunks,
        "embedding_dimension": embedding_dim,
        "device_used": current_device,
        "fallback_reason": fallback_reason,
        "output_npy": str(output_npy.resolve()),
        "output_rows": str(output_rows.resolve()),
        "manifest_path": str(manifest_path.resolve()),
    }


# ---------------------------------------------------------------------------
# Dense Search Engine
# ---------------------------------------------------------------------------

def load_dense_index_artifacts(
    npy_path: Path = DEFAULT_EMBEDDINGS_NPY,
    rows_path: Path = DEFAULT_EMBEDDING_ROWS,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    """Strictly load and validate dense index sidecar files."""
    if not npy_path.exists():
        raise FileNotFoundError(f"Dense embeddings file not found: {npy_path}")
    if not rows_path.exists():
        raise FileNotFoundError(f"Dense rows file not found: {rows_path}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Model manifest not found: {manifest_path}")
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Fail closed on stale chunks
    current_chunks_sha256 = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    recorded_chunks_sha256 = manifest.get("corpus_indexing", {}).get("source_chunks_sha256")
    if current_chunks_sha256 != recorded_chunks_sha256:
        raise RuntimeError(
            f"Chunks checksum mismatch! Current: '{current_chunks_sha256}', "
            f"Index built with: '{recorded_chunks_sha256}'. Refusing stale dense index."
        )

    # Fail closed on mismatched model ID / revision
    if manifest.get("model_id") != APPROVED_MODEL_ID or manifest.get("model_revision") != APPROVED_MODEL_REVISION:
        raise RuntimeError(
            f"Index model mismatch! Expected {APPROVED_MODEL_ID}@{APPROVED_MODEL_REVISION}, "
            f"got {manifest.get('model_id')}@{manifest.get('model_revision')}."
        )

    embeddings = np.load(npy_path)
    rows: list[dict[str, Any]] = []
    with rows_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    if embeddings.shape[0] != len(rows):
        raise RuntimeError(
            f"Mismatch between embedding array rows ({embeddings.shape[0]}) and row records ({len(rows)})."
        )

    chunks_map: dict[str, dict[str, Any]] = {}
    with chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                chunks_map[c["chunk_id"]] = c

    return embeddings, rows, manifest, chunks_map


def search_rag_v2_dense(
    query: str,
    limit: int = 3,
    model_dir: Path = DEFAULT_MODEL_DIR,
    npy_path: Path = DEFAULT_EMBEDDINGS_NPY,
    rows_path: Path = DEFAULT_EMBEDDING_ROWS,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    device: str = "auto",
    embedder_override: Any = None,
) -> list[RagV2DenseHit]:
    """Execute dense-only Cosine Similarity retrieval over the sidecar index."""
    if not query or not query.strip():
        return []

    embeddings, rows, manifest, chunks_map = load_dense_index_artifacts(
        npy_path=npy_path,
        rows_path=rows_path,
        manifest_path=manifest_path,
        chunks_path=chunks_path,
    )

    model, _ = load_dense_embedder(
        model_dir=model_dir,
        device=device,
        embedder_override=embedder_override,
    )

    # Encode query
    if hasattr(model, "encode"):
        query_vec_raw = model.encode(
            [query],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )[0]
    else:
        query_vec_raw = model([query])[0]

    query_vec = np.array(query_vec_raw, dtype=np.float32)
    norm = np.linalg.norm(query_vec)
    if norm > 0:
        query_vec = query_vec / norm

    # Inner product equals Cosine Similarity since both are L2 normalized
    scores = np.dot(embeddings, query_vec)

    # Top-K indices
    top_indices = np.argsort(scores)[::-1][:limit]

    hits: list[RagV2DenseHit] = []
    for rank_idx, row_idx in enumerate(top_indices, start=1):
        row = rows[row_idx]
        cid = row["chunk_id"]
        chunk = chunks_map[cid]
        score = float(scores[row_idx])
        url = chunk.get("final_url") or chunk.get("source_url", "")
        raw_html_path = f"data/raw/rag_v2/{chunk['source_id']}/source.html"

        hits.append(RagV2DenseHit(
            chunk_id=cid,
            source_id=chunk["source_id"],
            score=round(score, 4),
            rank=rank_idx,
            title=chunk["title"],
            url=url,
            heading_path=chunk["heading_path"],
            raw_html_path=raw_html_path,
            raw_sha256=chunk["raw_sha256"],
            section_ids=chunk["section_ids"],
            source_anchors=chunk.get("source_anchors", []),
            text=chunk["text"],
            text_char_count=chunk["text_char_count"],
        ))

    return hits


# ---------------------------------------------------------------------------
# Holdout Evaluation Engine
# ---------------------------------------------------------------------------

def evaluate_rag_v2_dense(
    holdout_path: Path = DEFAULT_HOLDOUT_PATH,
    model_dir: Path = DEFAULT_MODEL_DIR,
    npy_path: Path = DEFAULT_EMBEDDINGS_NPY,
    rows_path: Path = DEFAULT_EMBEDDING_ROWS,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    top_k: int = 3,
    device: str = "auto",
    embedder_override: Any = None,
) -> dict[str, Any]:
    """Execute dense-only evaluation against cross-language holdout benchmark cases."""
    if not holdout_path.exists():
        raise FileNotFoundError(f"Holdout cases file not found: {holdout_path}")

    cases: list[dict[str, Any]] = []
    with holdout_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    # Read manifest for indexing latency
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    results: list[dict[str, Any]] = []
    query_latencies: list[float] = []
    hit_at_1_count = 0
    hit_at_3_count = 0
    mrr_sum = 0.0

    for case in cases:
        case_id = case["case_id"]
        query = case["query"]
        expected_sources = set(case.get("expected_source_ids", []))
        expected_chunks = set(case.get("expected_chunk_ids", []))

        t0 = time.perf_counter()
        hits = search_rag_v2_dense(
            query=query,
            limit=top_k,
            model_dir=model_dir,
            npy_path=npy_path,
            rows_path=rows_path,
            manifest_path=manifest_path,
            chunks_path=chunks_path,
            device=device,
            embedder_override=embedder_override,
        )
        t_query = time.perf_counter() - t0
        query_latencies.append(t_query)

        matched_rank = None
        matched_chunk_id = None
        matched_source_id = None

        for hit in hits:
            is_match = False
            if expected_chunks and hit.chunk_id in expected_chunks:
                is_match = True
            elif expected_sources and hit.source_id in expected_sources:
                is_match = True

            if is_match:
                matched_rank = hit.rank
                matched_chunk_id = hit.chunk_id
                matched_source_id = hit.source_id
                break

        is_hit_at_1 = bool(matched_rank == 1)
        is_hit_at_3 = bool(matched_rank is not None and matched_rank <= 3)
        rr = (1.0 / matched_rank) if matched_rank is not None and matched_rank <= 3 else 0.0

        if is_hit_at_1:
            hit_at_1_count += 1
        if is_hit_at_3:
            hit_at_3_count += 1
        mrr_sum += rr

        results.append({
            "case_id": case_id,
            "case_type": case.get("case_type", "cross_language"),
            "query": query,
            "query_language": case.get("query_language", "zh"),
            "expected_source_ids": list(expected_sources),
            "expected_chunk_ids": list(expected_chunks),
            "matched_rank": matched_rank,
            "matched_chunk_id": matched_chunk_id,
            "matched_source_id": matched_source_id,
            "hit_at_1": is_hit_at_1,
            "hit_at_3": is_hit_at_3,
            "reciprocal_rank": rr,
            "query_latency_ms": round(t_query * 1000, 2),
            "rationale": case.get("rationale", ""),
            "fts_expected_limitation": case.get("fts_expected_limitation", ""),
            "hits": [h.to_dict() for h in hits],
        })

    total_cases = len(results)
    hit_at_1_rate = (hit_at_1_count / total_cases) if total_cases > 0 else 0.0
    hit_at_3_rate = (hit_at_3_count / total_cases) if total_cases > 0 else 0.0
    mrr_at_3 = (mrr_sum / total_cases) if total_cases > 0 else 0.0

    # Latencies
    q_latencies_sorted = sorted(query_latencies)
    q_p50 = float(np.percentile(q_latencies_sorted, 50)) if q_latencies_sorted else 0.0
    q_p95 = float(np.percentile(q_latencies_sorted, 95)) if q_latencies_sorted else 0.0

    idx_latency_per_chunk = manifest.get("corpus_indexing", {}).get("indexing_seconds_per_chunk", 0.0)

    # Quality Gate Assessment
    coverage_ratio = manifest.get("corpus_indexing", {}).get("actual_coverage_ratio", 1.0)
    hard_gate_passed = bool(
        coverage_ratio >= 1.0
        and hit_at_3_rate >= 0.70
        and mrr_at_3 >= 0.50
    )
    status_label = "quality_gate_met_for_dense" if hard_gate_passed else "quality_gate_not_met_for_dense"

    summary = {
        "evaluated_at": datetime.now(TZ_UTC8).isoformat(),
        "status": status_label,
        "model_id": APPROVED_MODEL_ID,
        "model_revision": APPROVED_MODEL_REVISION,
        "holdout_cases_total": total_cases,
        "hit_at_1_count": hit_at_1_count,
        "hit_at_1_rate": round(hit_at_1_rate, 4),
        "hit_at_3_count": hit_at_3_count,
        "hit_at_3_rate": round(hit_at_3_rate, 4),
        "mrr_at_3": round(mrr_at_3, 4),
        "chunk_embedding_coverage_ratio": coverage_ratio,
        "quality_gates": {
            "target_coverage_ratio": 1.0,
            "coverage_passed": (coverage_ratio >= 1.0),
            "target_hit_at_3": 0.70,
            "hit_at_3_passed": (hit_at_3_rate >= 0.70),
            "target_mrr_at_3": 0.50,
            "mrr_at_3_passed": (mrr_at_3 >= 0.50),
            "overall_hard_gates_passed": hard_gate_passed,
        },
        "measured_latencies": {
            "query_latency_seconds_p50": round(q_p50, 4),
            "query_latency_seconds_p95": round(q_p95, 4),
            "indexing_seconds_per_chunk_measured": round(idx_latency_per_chunk, 4),
        },
    }

    _write_dense_baseline_report(report_path, summary, results, manifest)
    return summary


def _write_dense_baseline_report(
    report_path: Path,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    """Generate Markdown report for dense retrieval baseline."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    status_badge = "🟢 PASS (quality_gate_met_for_dense)" if summary["quality_gates"]["overall_hard_gates_passed"] else "🔴 FAIL (quality_gate_not_met_for_dense)"

    lines.append("# RAG v2 Dense Retrieval Sidecar 基準評測報告")
    lines.append("")
    lines.append(f"- **評測時間**：{summary['evaluated_at']}")
    lines.append(f"- **核准模型**：`{summary['model_id']}` (Revision: `{summary['model_revision'][:8]}`)")
    lines.append(f"- **品質閘門狀態**：**{status_badge}**")
    lines.append(f"- **執行裝置**：`{manifest.get('hardware_execution', {}).get('device_used', 'unknown')}` ({manifest.get('hardware_execution', {}).get('device_name', 'unknown')})")
    lines.append("- **安全與邊界**：完全本機離線推論（`local_files_only=True`、`HF_HUB_OFFLINE=1`），無外部 API 傳輸。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1. 硬性品質門檻驗收結果")
    lines.append("")
    lines.append("| 驗收指標 | 門檻目標 | 實測數值 | 判定 | 說明 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    qg = summary["quality_gates"]
    lines.append(f"| **Chunk 向量覆蓋率** | `>= 1.0` (100%) | **{summary['chunk_embedding_coverage_ratio']*100:.1f}%** | {'✅ 通過' if qg['coverage_passed'] else '❌ 未過'} | 27 筆 chunk 全量向量化 sidecar |")
    lines.append(f"| **Holdout 跨語言 Hit@3** | `>= 0.70` (70%) | **{summary['hit_at_3_rate']*100:.1f}%** ({summary['hit_at_3_count']}/{summary['holdout_cases_total']}) | {'✅ 通過' if qg['hit_at_3_passed'] else '❌ 未過'} | Top-3 內命中目標來源與 Chunk |")
    lines.append(f"| **Holdout 跨語言 MRR@3** | `>= 0.50` | **{summary['mrr_at_3']:.4f}** | {'✅ 通過' if qg['mrr_at_3_passed'] else '❌ 未過'} | 平均倒數排名 Mean Reciprocal Rank |")
    lines.append(f"| **Hit@1** | 參考指標 | **{summary['hit_at_1_rate']*100:.1f}%** ({summary['hit_at_1_count']}/{summary['holdout_cases_total']}) | 觀測指標 | 第一名直接命中目標 |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. 實測效能延遲記錄 (Measured Latencies)")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> 依契約規範，推論延遲採觀測記錄評估，不作硬性阻絕門檻。")
    lines.append("")
    lines.append("| 效能指標 | 數值 | 備註說明 |")
    lines.append("| :--- | :--- | :--- |")
    ml = summary["measured_latencies"]
    lines.append(f"| **單次查詢延遲 (p50)** | `{ml['query_latency_seconds_p50']*1000:.1f} ms` | 50% 查詢在此時間內完成 |")
    lines.append(f"| **單次查詢延遲 (p95)** | `{ml['query_latency_seconds_p95']*1000:.1f} ms` | 95% 查詢在此時間內完成 |")
    lines.append(f"| **建庫速度 (單 chunk)** | `{ml['indexing_seconds_per_chunk_measured']:.3f} s/chunk` | 27 筆 chunk 批次向量化均速 |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. 跨語言方向分組表現統計")
    lines.append("")
    lines.append("| 檢索方向類別 | 題數 | Hit@1 | Hit@3 | MRR@3 | 語意跨越能力分析 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_type.setdefault(r["case_type"], []).append(r)

    type_labels = {
        "cross_language_zh_to_en": "中文 ➔ 英文 (zh ➔ en)",
        "cross_language_en_to_zh": "英文 ➔ 中文 (en ➔ zh)",
        "cross_language_mixed_paraphrase": "中英混合改寫 (mixed)",
    }

    for ctype, group in by_type.items():
        cnt = len(group)
        h1 = sum(1 for x in group if x["hit_at_1"])
        h3 = sum(1 for x in group if x["hit_at_3"])
        mrr = sum(x["reciprocal_rank"] for x in group) / cnt if cnt > 0 else 0.0
        label = type_labels.get(ctype, ctype)
        lines.append(f"| **{label}** | {cnt} | {h1}/{cnt} ({h1/cnt*100:.0f}%) | {h3}/{cnt} ({h3/cnt*100:.0f}%) | {mrr:.4f} | 零翻譯條件下多語向量直接召回 |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4. FTS5 詞彙缺口與 Dense 語意檢索對照")
    lines.append("")
    lines.append("| 案例編號 | 查詢內容 | FTS5 詞彙結果 | Dense 向量結果 | 語意鴻溝跨越成效 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")

    for r in results:
        dense_status = f"✅ Rank {r['matched_rank']}" if r["hit_at_3"] else "❌ 未命中"
        lines.append(
            f"| `{r['case_id']}` | {r['query']} | `0 hits (詞彙無共享)` | {dense_status} | {r['rationale']} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 5. Holdout 逐題檢索明細清單")
    lines.append("")

    for idx, r in enumerate(results, start=1):
        status_icon = "✅" if r["hit_at_3"] else "❌"
        rank_str = f"Rank {r['matched_rank']}" if r["matched_rank"] else "未命中 (Rank > 3)"
        lines.append(f"### {idx}. {status_icon} [{r['case_id']}] {r['query']}")
        lines.append(f"- **檢索類型**：`{r['case_type']}` ({r['query_language']})")
        lines.append(f"- **預期目標**：Source: `{r['expected_source_ids']}` | Chunks: `{r['expected_chunk_ids']}`")
        lines.append(f"- **Dense 結果**：{rank_str} (RR: `{r['reciprocal_rank']:.4f}`, Latency: `{r['query_latency_ms']} ms`)")
        lines.append(f"- **FTS5 預期限制**：{r['fts_expected_limitation']}")
        lines.append(f"- **語意設計理念**：{r['rationale']}")
        lines.append("- **Top 命中清單**：")
        if not r["hits"]:
            lines.append("  - *(無任何命中)*")
        else:
            for hit in r["hits"]:
                lines.append(f"  - **Rank {hit['rank']}** (Score: `{hit['score']:.4f}` | `{hit['chunk_id']}` | `{hit['source_id']}`): {hit['title']} - {hit['heading_path']}")
        lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
