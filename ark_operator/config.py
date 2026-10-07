"""Application configuration loaded from environment (.env.example)."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Cost-efficient default — never Opus/Sonnet unless OPERATOR_MODEL is overridden.
DEFAULT_OPERATOR_MODEL = "claude-haiku-5-5"


class Settings(BaseSettings):
    """Runtime settings. Secrets never committed; see .env.example."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Map ANTHROPIC_API_KEY / OPERATOR_MODEL without requiring Field aliases.
        env_nested_delimiter="__",
    )

    anthropic_api_key: str = ""
    operator_model: str = DEFAULT_OPERATOR_MODEL
    portal_operator_password: str = ""
    portal_base_url: str = "http://127.0.0.1:8765"
    portal_db_path: str = "company_world/portal/portal.db"
    operator_db_path: str = "data/operator.db"
    operator_headless: bool = True
    faults: str = ""
    session_expiry_n: int = 5
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Load settings from process env and optional local `.env` file."""
    return Settings()
