from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", "").strip())
    typesafe_api_key: str = field(
        default_factory=lambda: os.environ.get("TYPESAFE_API_KEY", "").strip()
    )
    jev_model: str = field(default_factory=lambda: os.environ.get("JEV_MODEL", "jev-latest"))
    jev_api_url: str = field(
        default_factory=lambda: os.environ.get("JEV_API_URL", "https://api.typesafe.ai/v1/systemone")
    )
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("DATA_DIR", str(REPO_ROOT / "data")))
    )
    scan_lookback_days: int = field(default_factory=lambda: _int("SCAN_LOOKBACK_DAYS", 365))
    max_issues: int = field(default_factory=lambda: _int("MAX_ISSUES", 400))
    max_prs: int = field(default_factory=lambda: _int("MAX_PRS", 200))
    max_discussions: int = field(default_factory=lambda: _int("MAX_DISCUSSIONS", 100))
    max_comment_fetches: int = field(default_factory=lambda: _int("MAX_COMMENT_FETCHES", 300))
    max_timeline_fetches: int = field(default_factory=lambda: _int("MAX_TIMELINE_FETCHES", 12))
    max_pull_details: int = field(default_factory=lambda: _int("MAX_PULL_DETAILS", 8))
    github_min_budget: int = field(default_factory=lambda: _int("GITHUB_MIN_BUDGET", 20))
    http_timeout: float = 30.0
    top_n: int = 3

    @property
    def db_path(self) -> Path:
        return self.data_dir / "radar.db"

    @property
    def context_dir(self) -> Path:
        return self.data_dir / "context"

    @property
    def judge_mode(self) -> str:
        return "jev" if self.typesafe_api_key else "heuristic"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.data_dir.mkdir(parents=True, exist_ok=True)
        _settings.context_dir.mkdir(parents=True, exist_ok=True)
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
