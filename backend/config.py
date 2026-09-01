"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ─────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "kopis"
    postgres_user: str = "kopis"
    postgres_password: str = ""

    # ── ChromaDB ─────────────────────────────────────────────
    chromadb_host: str = "localhost"
    chromadb_port: int = 8000

    # ── Grafana ──────────────────────────────────────────────
    grafana_url: str = "http://grafana:3000"
    grafana_api_key: str = ""

    # ── pyATS ────────────────────────────────────────────────
    pyats_username: str = ""
    pyats_password: str = ""
    pyats_connect_timeout: int = 60
    pyats_command_timeout: int = 30

    # ── Ollama ───────────────────────────────────────────────
    ollama_url: str = "http://ollama-host:11434"
    ollama_model: str = "qwen2.5:14b"

    # ── Anthropic ────────────────────────────────────────────
    anthropic_api_key: str = ""
    haiku_model: str = "claude-haiku-4-5-20251001"
    sonnet_model: str = "claude-sonnet-4-6"
    opus_model: str = "claude-opus-4-6"

    # ── Jira ─────────────────────────────────────────────────
    jira_url: str = ""  # e.g. https://your-org.atlassian.net
    jira_user_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "KSR"

    # ── Slack ────────────────────────────────────────────────
    slack_webhook_url: str = ""
    slack_signing_secret: str = ""

    # ── Application ──────────────────────────────────────────
    snapshot_schedule_cron: str = "0 */6 * * *"
    inventory_refresh_minutes: int = 60
    approval_expiry_hours: int = 24
    log_level: str = "INFO"

    # ── API Auth / CORS ──────────────────────────────────────
    # Shared-secret API credential. Required for every non-health request —
    # there is no "auth disabled" default. See backend/api/deps.py.
    api_auth_token: str = ""
    # Comma-separated list of allowed CORS origins (the frontend origin(s)).
    cors_allowed_origins: str = "http://localhost:8201"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic migrations."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
