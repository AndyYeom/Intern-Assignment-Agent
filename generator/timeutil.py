"""Timestamp parsing shared by every module that reads GitHub dates."""
from __future__ import annotations

from datetime import datetime


def parse_ts(value: str | None) -> datetime | None:
    """ISO-8601 to datetime; None for missing or malformed values."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
