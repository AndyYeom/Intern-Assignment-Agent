"""Catalog agent for managers: suggest role requirements from a project description."""

import uuid

from fastapi import APIRouter
from pydantic import Field

from backend import repositories as repo
from backend.api.errors import ApiError, not_found
from backend.api.routes_manager import DB
from backend.api.schemas import ApiModel, RequirementType
from backend.services import catalog

router = APIRouter(prefix="/api/manager", tags=["catalog"])


class SuggestedRequirement(ApiModel):
    skill_id: str
    skill_name: str
    requirement_type: RequirementType
    required_level: int
    # False when the model left the level open and the default was filled in.
    level_suggested: bool
    weight: float
    confidence: float
    evidence_text: str
    decision_basis: str


class UnresolvedRequirement(ApiModel):
    raw_skill: str
    requirement_type: RequirementType
    candidate_skill_ids: list[str] = Field(default_factory=list)


class RequirementSuggestion(ApiModel):
    provider: str
    summary: str
    requirements: list[SuggestedRequirement]
    unresolved: list[UnresolvedRequirement]
    uncertainties: list[str]
    issues: list[str]


@router.post("/projects/{project_id}/suggest-requirements", response_model=RequirementSuggestion)
async def suggest_requirements(project_id: uuid.UUID, session: DB) -> RequirementSuggestion:
    """Run the catalog agent on the project description. Writes nothing."""
    project = repo.get_project(session, project_id)
    if project is None:
        raise not_found("Project")
    name, description = project.name, project.description or ""
    # Release the connection before the (slow) model calls.
    session.close()
    try:
        result = await catalog.suggest_requirements(str(project_id), name, description)
    except catalog.CatalogUnavailable as exc:
        raise ApiError(503, "catalog_unavailable", str(exc)) from None
    except catalog.CatalogFailed as exc:
        raise ApiError(422, "catalog_failed", str(exc)) from None
    return RequirementSuggestion(**result)
