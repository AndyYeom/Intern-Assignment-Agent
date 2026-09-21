"""Validated-project repository and handoff errors."""


class ProjectRepositoryError(RuntimeError):
    """Base exception for known project repository failures."""


class ProjectRepositoryConflictError(ProjectRepositoryError):
    """A unique request or project identity already exists."""


class ProjectRepositoryDataError(ProjectRepositoryError):
    """Persisted project data cannot be safely revalidated."""


class PublishableProjectNotFoundError(LookupError):
    """The Scoring-Agent boundary cannot return a valid stored profile."""
