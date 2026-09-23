"""Environment-based application settings."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional .env file."""

    app_name: str = "project-catalog-agent"
    app_version: str = "0.1.0"
    environment: str = "development"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"

    # The repository shares .env with the profile, evidence and admin agents.
    # Their settings must not prevent the catalog agent from starting.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
