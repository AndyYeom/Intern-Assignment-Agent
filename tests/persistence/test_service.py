"""Tests for guarded request-idempotent publication."""

from datetime import UTC, datetime

import pytest

from project_catalog_agent.agent import CatalogDecisionPolicy, CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    DecisionReason,
    DecisionType,
)
from project_catalog_agent.persistence import (
    ComponentVersions,
    InMemoryProjectRepository,
    ProjectPublicationGuard,
    ProjectPublicationService,
    ProjectRepositoryError,
    PublicationStatus,
    get_publishable_project_profile,
)
from tests.persistence.helpers import NOW, valid_state


class FailingRepository:
    """Controlled infrastructure failure for publication tests."""

    def create(self, project: object) -> object:
        del project
        raise ProjectRepositoryError("controlled failure")

    def get_by_request_id(self, request_id: str) -> None:
        del request_id
        raise ProjectRepositoryError("controlled failure")

    def get_by_project_id(self, project_id: str) -> None:
        del project_id
        raise ProjectRepositoryError("controlled failure")

    def list_projects(self) -> tuple[()]:
        raise ProjectRepositoryError("controlled failure")


def service(
    repository: InMemoryProjectRepository | FailingRepository,
    *,
    ids: list[str] | None = None,
    clock: datetime = NOW,
) -> ProjectPublicationService:
    """Build a deterministic publication service."""
    project_ids = iter(ids or ["PRJ-001"])
    return ProjectPublicationService(
        repository=repository,  # type: ignore[arg-type]
        guard=ProjectPublicationGuard(lambda: "0.1"),
        state_updater=CatalogStateUpdater(),
        project_id_factory=lambda: next(project_ids),
        clock=lambda: clock,
        taxonomy_version_provider=lambda: "0.1",
        component_versions=ComponentVersions(
            extractor_version="extractor-v1",
            normalizer_version="normalizer-v1",
            profile_builder_version="builder-v1",
            validator_version="validator-v1",
        ),
    )


def test_first_publication_completes_once_and_preserves_input() -> None:
    repository = InMemoryProjectRepository()
    state = valid_state()
    before = state.model_dump_json()

    result = service(repository).publish(state)

    assert result.status is PublicationStatus.PUBLISHED
    assert result.changed
    assert result.stored_project is not None
    assert result.updated_state is not None
    assert result.updated_state.status is CatalogStatus.COMPLETED
    assert result.updated_state.stage is CatalogStage.COMPLETED
    assert result.updated_state.published_project_id == "PRJ-001"
    assert result.updated_state.state_version == state.state_version + 1
    assert result.stored_project.created_at == NOW
    assert result.stored_project.taxonomy_version == "0.1"
    assert result.stored_project.extractor_version == "extractor-v1"
    assert state.model_dump_json() == before
    assert len(repository.list_projects()) == 1


def test_exact_retry_returns_existing_without_calling_id_factory() -> None:
    repository = InMemoryProjectRepository()
    state = valid_state()
    first_service = service(repository)
    first = first_service.publish(state)
    assert first.stored_project is not None

    result = service(repository, ids=[]).publish(state)

    assert result.status is PublicationStatus.ALREADY_PUBLISHED
    assert not result.changed
    assert result.stored_project is not None
    assert result.stored_project.project_id == first.stored_project.project_id
    assert len(repository.list_projects()) == 1


def test_conflicting_retry_is_rejected_without_overwrite() -> None:
    repository = InMemoryProjectRepository()
    state = valid_state()
    published = service(repository).publish(state)
    assert published.stored_project is not None
    assert state.candidate_profile is not None
    changed_profile = state.candidate_profile.model_copy(
        update={"project_name": "Materially Different"}, deep=True
    )
    conflicting = state.model_copy(
        update={"candidate_profile": changed_profile}, deep=True
    )

    result = service(repository, ids=[]).publish(conflicting)

    assert result.status is PublicationStatus.REJECTED
    assert result.error_code == "IDEMPOTENCY_CONFLICT"
    assert repository.list_projects() == (published.stored_project,)


def test_invalid_state_is_not_persisted() -> None:
    repository = InMemoryProjectRepository()
    invalid = valid_state().model_copy(update={"validation_result": None}, deep=True)

    result = service(repository).publish(invalid)

    assert result.status is PublicationStatus.REJECTED
    assert result.error_code == "VALIDATION_MISSING"
    assert repository.list_projects() == ()


def test_repository_failure_never_completes_state() -> None:
    state = valid_state()

    result = service(FailingRepository()).publish(state)

    assert result.status is PublicationStatus.FAILED
    assert result.error_code == "REPOSITORY_FAILURE"
    assert result.updated_state is None
    assert state.status is CatalogStatus.PROCESSING
    assert state.published_project_id is None


def test_decision_policy_distinguishes_validated_and_published() -> None:
    state = valid_state()
    ready = CatalogDecisionPolicy().decide(state)
    publication = service(InMemoryProjectRepository()).publish(state)
    assert publication.updated_state is not None
    complete = CatalogDecisionPolicy().decide(publication.updated_state)

    assert ready.decision_type is DecisionType.PUBLISH_PROFILE
    assert ready.reason_code is DecisionReason.PROFILE_READY_TO_PUBLISH
    assert complete.decision_type is DecisionType.COMPLETE
    assert complete.reason_code is DecisionReason.PROFILE_PUBLISHED


def test_completed_state_requires_project_id_and_round_trips() -> None:
    state = valid_state()
    payload = state.model_dump()
    payload.update(status="completed", stage="completed")
    with pytest.raises(ValueError):
        CatalogAgentState.model_validate(payload)
    result = service(InMemoryProjectRepository()).publish(state)
    assert result.updated_state is not None

    restored = CatalogAgentState.model_validate_json(
        result.updated_state.model_dump_json()
    )

    assert restored == result.updated_state


def test_handoff_returns_detached_validated_profile() -> None:
    repository = InMemoryProjectRepository()
    result = service(repository).publish(valid_state())
    assert result.stored_project is not None

    profile = get_publishable_project_profile(
        repository, result.stored_project.project_id
    )
    profile.requirements.clear()

    stored = repository.get_by_project_id(result.stored_project.project_id)
    assert stored is not None
    assert stored.project_profile.requirements


def test_stored_json_contains_no_authentication_secrets() -> None:
    result = service(InMemoryProjectRepository()).publish(valid_state())
    assert result.stored_project is not None
    serialized = result.stored_project.model_dump_json().casefold()

    for forbidden in ("password", "password_hash", "token", "secret", "authorization"):
        assert forbidden not in serialized


def test_clock_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError):
        service(InMemoryProjectRepository(), clock=datetime(2026, 1, 1)).publish(
            valid_state()
        )
    assert datetime.now(UTC).utcoffset() is not None
