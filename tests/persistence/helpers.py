"""Controlled validated publication fixtures."""

from datetime import UTC, datetime

from project_catalog_agent.catalog.contracts import CatalogAgentState
from project_catalog_agent.persistence import StoredProject
from tests.agent.test_state import pipeline_state

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)


def valid_state() -> CatalogAgentState:
    """Return one valid but unpublished state."""
    return pipeline_state(valid=True)


def stored_project(
    project_id: str = "PRJ-001",
    state: CatalogAgentState | None = None,
) -> StoredProject:
    """Build one valid stored record from a controlled state."""
    source = state or valid_state()
    assert source.candidate_profile is not None
    assert source.validation_result is not None
    return StoredProject(
        project_id=project_id,
        request_id=source.request.request_id,
        project_profile=source.candidate_profile,
        validation_result=source.validation_result,
        taxonomy_version="0.1",
        extractor_version="extractor-v1",
        normalizer_version="normalizer-v1",
        profile_builder_version="builder-v1",
        validator_version="validator-v1",
        created_at=NOW,
    )
