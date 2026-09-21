"""Errors raised at catalog-state transition boundaries."""


class InvalidStateTransitionError(Exception):
    """Raised when orchestration attempts an impossible state transition."""
