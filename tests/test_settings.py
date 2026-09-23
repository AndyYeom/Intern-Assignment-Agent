"""Regression coverage for the shared, multi-agent environment file."""

from pathlib import Path

import pytest

from project_catalog_agent.config.settings import Settings


def test_catalog_accepts_other_agents_environment_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_NAME", raising=False)
    environment = tmp_path / ".env"
    environment.write_text(
        "APP_NAME=local-catalog\n"
        "LLM_GATEWAY_URL=https://example.invalid\n"
        "LLM_GATEWAY_API_KEY=test-only\n"
        "LLM_MODEL=test-model\n"
        "GITHUB_TOKEN=test-only\n"
        "CLARIFIER_USERNAME=reviewer\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=environment)
    assert settings.app_name == "local-catalog"
    assert not hasattr(settings, "llm_gateway_api_key")
