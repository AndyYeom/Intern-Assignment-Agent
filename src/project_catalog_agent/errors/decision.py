"""Errors raised at deterministic decision boundaries."""


class InvalidDecisionStateError(Exception):
    """Raised when a state cannot be interpreted safely by the policy."""
