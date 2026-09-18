from pathlib import Path

from coral_rag.query import answer


def test_offline_answer_never_claims_safe() -> None:
    response = answer("浪高 0.3 公尺可以安全浮潛嗎？", [], None)
    assert "安全" not in response or "資料不足" in response


def test_examples_do_not_contain_live_key() -> None:
    root = Path(__file__).resolve().parents[1]
    example = (root / ".env.example").read_text(encoding="utf-8")
    assert "sk-" not in example
    assert "IAI_API_KEY=" in example
