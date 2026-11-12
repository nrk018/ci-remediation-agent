"""Runtime configuration loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    github_token: str = ""
    github_webhook_secret: str = ""
    openai_api_key: str = ""
    database_url: str = ""
    harness_api_token: str = ""
    harness_account_id: str = ""
    harness_base_url: str = "https://app.harness.io"
    confidence_threshold: float = 0.35
    similarity_floor: float = 0.35
    retry_cap: int = 2
    embedding_dim: int = 1536
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    log_tail_lines: int = 40
    offline: bool = False

    @property
    def use_openai(self) -> bool:
        return bool(self.openai_api_key) and not self.offline

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            github_token=os.environ.get("GITHUB_TOKEN", ""),
            github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            database_url=os.environ.get("DATABASE_URL", ""),
            harness_api_token=os.environ.get("HARNESS_API_TOKEN", ""),
            harness_account_id=os.environ.get("HARNESS_ACCOUNT_ID", ""),
            harness_base_url=os.environ.get("HARNESS_BASE_URL", "https://app.harness.io"),
            confidence_threshold=float(os.environ.get("CONFIDENCE_THRESHOLD", "0.35")),
            similarity_floor=float(os.environ.get("SIMILARITY_FLOOR", "0.35")),
            retry_cap=int(os.environ.get("RETRY_CAP", "2")),
            chat_model=os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
            embedding_model=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            log_tail_lines=int(os.environ.get("LOG_TAIL_LINES", "40")),
            offline=_flag("CI_REMEDIATION_OFFLINE"),
        )
