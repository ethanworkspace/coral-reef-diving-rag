#!/usr/bin/env python3
"""Offline environment inspector for RAG v2 vector retrieval readiness.

Strict safety constraints:
- Zero network requests (no HTTP/socket/pip/hf/gemini/ollama).
- Zero package installations or modifications.
- Zero secret, token, or environment variable reading.
- Read-only metadata/system inspection using Python standard library only.
- Graceful 'unavailable' outputs on missing GPU or packages.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TZ_UTC8 = timezone(timedelta(hours=8))
DEFAULT_OUTPUT_PATH = Path("metadata/rag_v2_vector_environment.json")


def inspect_python_runtime() -> dict[str, Any]:
    """Inspect Python runtime and architecture."""
    return {
        "version": platform.python_version(),
        "version_tuple": list(sys.version_info[:3]),
        "architecture": platform.architecture()[0],
        "machine": platform.machine(),
        "executable": sys.executable,
        "platform": platform.platform(),
    }


def inspect_system_resources() -> dict[str, Any]:
    """Inspect total/available RAM and disk space safely."""
    # RAM detection (Windows via ctypes, POSIX fallback)
    total_ram_gb = None
    avail_ram_gb = None

    if os.name == "nt":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_ram_gb = round(stat.ullTotalPhys / (1024**3), 2)
                avail_ram_gb = round(stat.ullAvailPhys / (1024**3), 2)
        except Exception:
            pass

    if total_ram_gb is None and hasattr(os, "sysconf"):
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_pages = os.sysconf("SC_PHYS_PAGES")
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            total_ram_gb = round((total_pages * page_size) / (1024**3), 2)
            avail_ram_gb = round((avail_pages * page_size) / (1024**3), 2)
        except Exception:
            pass

    # Disk detection (shutil.disk_usage)
    disk = shutil.disk_usage(".")
    disk_total_gb = round(disk.total / (1024**3), 2)
    disk_free_gb = round(disk.free / (1024**3), 2)
    disk_free_ratio = round(disk.free / disk.total, 4) if disk.total > 0 else 0.0

    return {
        "ram_total_gb": total_ram_gb if total_ram_gb is not None else "unavailable",
        "ram_available_gb": avail_ram_gb if avail_ram_gb is not None else "unavailable",
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "disk_free_ratio": disk_free_ratio,
    }


def inspect_ml_libraries() -> dict[str, dict[str, Any]]:
    """Inspect installation status and version of ML libraries without importing them."""
    targets = [
        "torch",
        "transformers",
        "sentence_transformers",
        "onnxruntime",
        "fastembed",
    ]
    results: dict[str, dict[str, Any]] = {}
    for pkg in targets:
        # Check standard normalized names
        candidates = [pkg, pkg.replace("_", "-")]
        found = False
        for c in candidates:
            try:
                ver = importlib.metadata.version(c)
                results[pkg] = {
                    "installed": True,
                    "version": ver,
                }
                found = True
                break
            except importlib.metadata.PackageNotFoundError:
                continue

        if not found:
            results[pkg] = {
                "installed": False,
                "version": None,
            }
    return results


def inspect_nvidia_gpu() -> dict[str, Any]:
    """Inspect NVIDIA GPU availability, device name, and VRAM without PyTorch."""
    smi_path = shutil.which("nvidia-smi")
    if not smi_path:
        return {
            "available": False,
            "device_name": "unavailable",
            "vram_total_mb": "unavailable",
            "vram_free_mb": "unavailable",
            "reason": "nvidia-smi binary not found on system PATH",
        }

    try:
        proc = subprocess.run(
            [
                smi_path,
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        output = proc.stdout.strip()
        if not output:
            return {
                "available": False,
                "device_name": "unavailable",
                "vram_total_mb": "unavailable",
                "vram_free_mb": "unavailable",
                "reason": "nvidia-smi returned empty query output",
            }

        first_line = output.splitlines()[0]
        parts = [p.strip() for p in first_line.split(",")]
        name = parts[0] if len(parts) > 0 else "unknown"
        total_mb = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else "unknown"
        free_mb = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else "unknown"

        return {
            "available": True,
            "device_name": name,
            "vram_total_mb": total_mb,
            "vram_free_mb": free_mb,
            "smi_path": smi_path,
        }
    except Exception as err:
        return {
            "available": False,
            "device_name": "unavailable",
            "vram_total_mb": "unavailable",
            "vram_free_mb": "unavailable",
            "reason": f"nvidia-smi query failed: {type(err).__name__}: {err}",
        }


def inspect_local_model_cache() -> dict[str, Any]:
    """Inspect local huggingface / torch sentence_transformers cache directories safely.
    
    Reads only folder names under cache roots; never reads files, tokens, or weights.
    """
    home = Path.home()
    cache_roots = [
        home / ".cache" / "huggingface" / "hub",
        home / ".cache" / "torch" / "sentence_transformers",
    ]
    detected_models: list[str] = []

    for root in cache_roots:
        if root.exists() and root.is_dir():
            try:
                for entry in root.iterdir():
                    if entry.is_dir():
                        detected_models.append(entry.name)
            except OSError:
                pass

    return {
        "cache_roots_checked": [str(r) for r in cache_roots],
        "cached_models": detected_models,
        "has_cached_embedding_models": bool(detected_models),
    }


def generate_environment_report() -> dict[str, Any]:
    """Compile comprehensive vector retrieval environment inspection report."""
    return {
        "inspected_at": datetime.now(TZ_UTC8).isoformat(),
        "python": inspect_python_runtime(),
        "system_resources": inspect_system_resources(),
        "ml_libraries": inspect_ml_libraries(),
        "gpu": inspect_nvidia_gpu(),
        "local_model_cache": inspect_local_model_cache(),
        "safety_and_privacy_compliance": {
            "read_environment_variables": False,
            "read_api_keys_or_tokens": False,
            "read_user_file_contents": False,
            "network_requests_made": False,
            "package_installation_performed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect RAG v2 vector retrieval environment")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"JSON report destination path (default: {DEFAULT_OUTPUT_PATH})",
    )
    args = parser.parse_args()

    report = generate_environment_report()
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Vector environment report written to: {out_path}")
    print(f"Python: {report['python']['version']} ({report['python']['architecture']})")
    print(f"RAM: total={report['system_resources']['ram_total_gb']}GB, available={report['system_resources']['ram_available_gb']}GB")
    print(f"Disk: free={report['system_resources']['disk_free_gb']}GB ({report['system_resources']['disk_free_ratio']*100:.1f}%)")
    print(f"GPU: available={report['gpu']['available']} ({report['gpu']['device_name']})")
    ml_status = {k: v["installed"] for k, v in report["ml_libraries"].items()}
    print(f"ML Libraries: {ml_status}")
    print(f"Cached models: {len(report['local_model_cache']['cached_models'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
