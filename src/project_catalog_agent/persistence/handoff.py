"""Validated stored-profile boundary for a future Scoring Agent."""

from project_catalog_agent.catalog.contracts import ProjectProfile
from project_catalog_agent.persistence.errors import (
    ProjectRepositoryError,
    PublishableProjectNotFoundError,
)
from project_catalog_agent.persistence.repository import ProjectRepository


def get_publishable_project_profile(
    repository: ProjectRepository,
    project_id: str,
) -> ProjectProfile:
    """Return only a stored valid and fully resolved project profile."""
    try:
        stored = repository.get_by_project_id(project_id)
    except ProjectRepositoryError as error:
        raise PublishableProjectNotFoundError(
            "publishable project profile is unavailable"
        ) from error
    if (
        stored is None
        or not stored.validation_result.valid
        or stored.project_profile.unresolved_requirements
        or stored.project_profile.unresolved_skills
    ):
        raise PublishableProjectNotFoundError(
            "publishable project profile is unavailable"
        )
    return stored.project_profile.model_copy(deep=True)
