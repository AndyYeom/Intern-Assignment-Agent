"""Application metadata."""

from typing import TypedDict


class AppInfo(TypedDict):
    """Shape of the application's public metadata."""

    name: str
    version: str
    status: str


def create_app_info() -> AppInfo:
    """Return basic application metadata."""
    return {
        "name": "project-catalog-agent",
        "version": "0.1.0",
        "status": "ready",
    }
