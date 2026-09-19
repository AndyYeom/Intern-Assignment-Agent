"""Guarded, request-idempotent validated-project publication service."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from project_catalog_agent.agent import CatalogStateUpdater
from project_catalog_agent.catalog.contracts import CatalogAgentState
from project_catalog_agent.persistence.contracts import (
    ComponentVersions,
    PublicationErrorCode,
    PublicationResult,
    PublicationStatus,
    StoredProject,
)
from project_catalog_agent.persistence.errors import (
    ProjectRepositoryConflictError,
    ProjectRepositoryError,
)
from project_catalog_agent.persistence.guard import ProjectPublicationGuard
from project_catalog_agent.persistence.repository import ProjectRepository


class ProjectPublicationService:
    """Persist a guarded profile before completing its catalog state."""

    def __init__(
        self,
        *,
        repository: ProjectRepository,
        guard: ProjectPublicationGuard,
        state_updater: CatalogStateUpdater,
        project_id_factory: Callable[[], str],
        clock: Callable[[], datetime],
        taxonomy_version_provider: Callable[[], str],
        component_versions: ComponentVersions,
    ) -> None:
        self._repository = repository
        self._guard = guard
        self._state_updater = state_updater
        self._project_id_factory = project_id_factory
        self._clock = clock
        self._taxonomy_version_provider = taxonomy_version_provider
        self._component_versions = component_versions

    def publish(self, state: CatalogAgentState) -> PublicationResult:
        """Publish once, return an exact retry, or reject conflicting content."""
        guard_result = self._guard.evaluate(state)
        if not guard_result.publishable:
            return PublicationResult(
                request_id=state.request.request_id,
                status=PublicationStatus.REJECTED,
                changed=False,
                message=guard_result.message,
                error_code=guard_result.error_code,
            )
        profile = state.candidate_profile
        validation = state.validation_result
        if profile is None or validation is None:
            return self._rejected(state, PublicationErrorCode.INVALID_PUBLICATION_STATE)
        taxonomy_version = self._taxonomy_version_provider().strip()
        try:
            existing = self._repository.get_by_request_id(state.request.request_id)
        except ProjectRepositoryError:
            return self._failed(state)
        if existing is not None:
            return self._existing_result(
                state,
                existing,
                taxonomy_version=taxonomy_version,
            )

        project = StoredProject(
            project_id=self._project_id_factory(),
            request_id=state.request.request_id,
            project_profile=profile.model_copy(deep=True),
            validation_result=validation.model_copy(deep=True),
            taxonomy_version=taxonomy_version,
            **self._component_versions.model_dump(),
            created_at=self._clock(),
        )
        try:
            stored = self._repository.create(project)
        except ProjectRepositoryConflictError:
            return self._resolve_create_race(
                state,
                taxonomy_version=taxonomy_version,
            )
        except ProjectRepositoryError:
            return self._failed(state)
        completed = self._state_updater.apply_publication(
            state, project_id=stored.project_id
        )
        return PublicationResult(
            request_id=state.request.request_id,
            status=PublicationStatus.PUBLISHED,
            changed=True,
            stored_project=stored,
            updated_state=completed,
            message="The validated project profile was published.",
        )

    def _resolve_create_race(
        self,
        state: CatalogAgentState,
        *,
        taxonomy_version: str,
    ) -> PublicationResult:
        try:
            existing = self._repository.get_by_request_id(state.request.request_id)
        except ProjectRepositoryError:
            return self._failed(state)
        if existing is None:
            return self._failed(state)
        return self._existing_result(
            state,
            existing,
            taxonomy_version=taxonomy_version,
        )

    def _existing_result(
        self,
        state: CatalogAgentState,
        existing: StoredProject,
        *,
        taxonomy_version: str,
    ) -> PublicationResult:
        if self._fingerprint_existing(existing) != self._fingerprint_state(
            state, taxonomy_version
        ):
            return self._rejected(state, PublicationErrorCode.IDEMPOTENCY_CONFLICT)
        completed = self._state_updater.apply_publication(
            state, project_id=existing.project_id
        )
        return PublicationResult(
            request_id=state.request.request_id,
            status=PublicationStatus.ALREADY_PUBLISHED,
            changed=False,
            stored_project=existing,
            updated_state=completed,
            message="The request was already published with equivalent content.",
        )

    def _fingerprint_state(
        self, state: CatalogAgentState, taxonomy_version: str
    ) -> dict[str, Any]:
        profile = state.candidate_profile
        validation = state.validation_result
        return {
            "request_id": state.request.request_id,
            "project_profile": profile.model_dump(mode="json") if profile else None,
            "validation_result": (
                validation.model_dump(mode="json") if validation else None
            ),
            "taxonomy_version": taxonomy_version,
            **self._component_versions.model_dump(mode="json"),
        }

    @staticmethod
    def _fingerprint_existing(project: StoredProject) -> dict[str, Any]:
        return {
            "request_id": project.request_id,
            "project_profile": project.project_profile.model_dump(mode="json"),
            "validation_result": project.validation_result.model_dump(mode="json"),
            "taxonomy_version": project.taxonomy_version,
            "extractor_version": project.extractor_version,
            "normalizer_version": project.normalizer_version,
            "profile_builder_version": project.profile_builder_version,
            "validator_version": project.validator_version,
        }

    @staticmethod
    def _rejected(
        state: CatalogAgentState,
        code: PublicationErrorCode,
    ) -> PublicationResult:
        return PublicationResult(
            request_id=state.request.request_id,
            status=PublicationStatus.REJECTED,
            changed=False,
            message="The validated project profile was not published.",
            error_code=code.value,
        )

    @staticmethod
    def _failed(state: CatalogAgentState) -> PublicationResult:
        return PublicationResult(
            request_id=state.request.request_id,
            status=PublicationStatus.FAILED,
            changed=False,
            message="The project repository could not complete publication.",
            error_code=PublicationErrorCode.REPOSITORY_FAILURE.value,
        )
