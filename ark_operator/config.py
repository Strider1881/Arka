"""Application configuration loaded from environment (.env.example)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secrets never committed; see .env.example."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    operator_model: str = "claude-sonnet-4-20250514"
    portal_operator_password: str = ""
    portal_base_url: str = "http://127.0.0.1:8765"
    portal_db_path: str = "company_world/portal/portal.db"
    operator_db_path: str = "data/operator.db"
    operator_headless: bool = True
    faults: str = ""
    session_expiry_n: int = 5
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Load settings from the environment."""
    return Settings()
