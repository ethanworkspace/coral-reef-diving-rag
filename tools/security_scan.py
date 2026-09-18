"""Fail a release check if a likely credential was placed in publishable project files."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "__pycache__", "data", "tests"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt", ".html", ".env"}
PATTERNS = {
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    "private key block": re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
    "hard-coded iAI key": re.compile(r"IAI_API_KEY\s*=\s*[^\s#][^\r\n]*"),
}


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name == ".env":  # local secret store; it is intentionally ignored by Git
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".env":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{name}: {path.relative_to(ROOT)}")
    if findings:
        print("SECURITY CHECK FAILED")
        print("\n".join(findings))
        return 1
    print("SECURITY CHECK PASSED: no likely credential found in publishable files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
