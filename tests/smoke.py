"""Dependency-light checks runnable without pytest."""

from pathlib import Path

from coral_rag.query import answer


ROOT = Path(__file__).resolve().parents[1]

assert "資料不足" in answer("浪高 0.3 公尺可以安全浮潛嗎？", [], None)
assert "sk-" not in (ROOT / ".env.example").read_text(encoding="utf-8")
print("SMOKE TEST PASSED")
