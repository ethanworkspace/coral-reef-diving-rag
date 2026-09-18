from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_local_env(path: Path) -> None:
    """Load a simple local .env without overriding real environment variables.

    The file is deliberately ignored by Git. This parser is intentionally small:
    it supports KEY=value lines only, which keeps secrets out of command history.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    project_root: Path
    db_path: Path
    base_url: str
    api_key: str | None
    chat_model: str
    embedding_model: str
    reranker_model: str
    max_live_data_age_hours: int

    @classmethod
    def from_project_root(cls, project_root: Path) -> "Settings":
        load_local_env(project_root / ".env")
        return cls(
            project_root=project_root,
            db_path=project_root / "data" / "processed" / "rag.sqlite",
            base_url=os.getenv("IAI_BASE_URL", "https://www.iai.nkust.edu.tw/aihub").rstrip("/"),
            api_key=os.getenv("IAI_API_KEY") or None,
            chat_model=os.getenv("IAI_CHAT_MODEL", "Furen-omni"),
            embedding_model=os.getenv("IAI_EMBEDDING_MODEL", "Embedding"),
            reranker_model=os.getenv("IAI_RERANKER_MODEL", "Furen-reranker"),
            max_live_data_age_hours=int(os.getenv("MAX_LIVE_DATA_AGE_HOURS", "6")),
        )
