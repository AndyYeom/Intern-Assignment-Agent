"""Tests for application metadata."""

from project_catalog_agent.app import create_app_info


def test_create_app_info() -> None:
    """Application metadata contains exactly the expected values."""
    app_info = create_app_info()

    assert app_info["name"] == "project-catalog-agent"
    assert app_info["version"] == "0.1.0"
    assert app_info["status"] == "ready"
    assert set(app_info) == {"name", "version", "status"}
