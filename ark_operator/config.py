"""Application configuration loaded from environment (.env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Cost-efficient default — never Opus/Sonnet unless OPERATOR_MODEL is overridden.
DEFAULT_OPERATOR_MODEL = "claude-haiku-5-5"

# Repo root (parent of ark_operator/) so `.env` resolves even when cwd differs.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime settings. Secrets never committed; see .env.example."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    anthropic_api_key: str = ""
    operator_model: str = DEFAULT_OPERATOR_MODEL
    portal_operator_password: str = "change-me"
    portal_manager_password: str = "priya-approve"
    portal_operator_email: str = "operator@acmecorp.test"
    portal_manager_email: str = "priya.nair@acmecorp.test"
    portal_base_url: str = "http://127.0.0.1:8765"
    portal_db_path: str = "company_world/portal/portal.db"
    portal_session_secret: str = "acme-dev-secret-change-me"
    # Single EventStore path shared by CLI + UI (OPERATOR_DB_PATH).
    operator_db_path: str = "data/operator.db"
    # Evidence / run artifacts; defaults beside the shared DB.
    operator_data_dir: str = "data"
    operator_headless: bool = True
    # Comma-separated invoice stems for a short UI/demo slice (empty = all inbox PDFs).
    operator_demo_invoices: str = ""
    # Optional HTTP Basic Auth for Operator UI when exposing beyond loopback.
    # Both must be non-empty to enable; local defaults leave them empty (no gate).
    operator_ui_basic_auth_user: str = ""
    operator_ui_basic_auth_pass: str = ""
    faults: str = ""
    session_expiry_n: int = 5
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from process env and optional local `.env` file.

    Cached for the process lifetime. Tests that mutate env should call
    ``get_settings.cache_clear()`` (see ``tests/conftest.py``).
    """
    return Settings()


def clear_settings_cache() -> None:
    """Drop cached Settings (used by tests after env changes)."""
    get_settings.cache_clear()
