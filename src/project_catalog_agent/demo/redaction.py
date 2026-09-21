"""Defensive redaction for optional terminal state rendering."""

from typing import Any

_SENSITIVE_FRAGMENTS = (
    "password",
    "password_hash",
    "plaintext_password",
    "secret",
    "token",
    "authorization",
)


def redact_sensitive(value: Any) -> Any:
    """Recursively redact values whose keys have sensitive fragments."""
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(
                    fragment in str(key).casefold() for fragment in _SENSITIVE_FRAGMENTS
                )
                else redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    return value


def contains_sensitive_key(value: Any) -> bool:
    """Return whether a nested mapping still exposes a sensitive field name."""
    if isinstance(value, dict):
        return any(
            any(fragment in str(key).casefold() for fragment in _SENSITIVE_FRAGMENTS)
            or contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_sensitive_key(item) for item in value)
    return False
