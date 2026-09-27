"""Environment-driven backend settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class BackendSettings(BaseSettings):
    """Backend configuration. Every value can be set through the environment."""

    # The repository shares .env with the agents; ignore their keys.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://utechia:local-dev-only@localhost:5433/utechia"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    # Comma-separated list. "*" allows any origin; only use it for local experiments.
    cors_allowed_origins: str = "http://localhost:3000"
    # Root for uploaded applicant documents (LocalStorage). Not durable on ECS.
    storage_root: Path = REPO_ROOT / "data" / "uploads"
    log_level: str = "INFO"
    # Largest accepted resume upload, in bytes.
    max_upload_bytes: int = 10 * 1024 * 1024

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> BackendSettings:
    return BackendSettings()
