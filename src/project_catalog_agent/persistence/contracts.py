"""Validated-project storage and publication contracts."""

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ContractModel,
    ProjectProfile,
    ValidationResult,
)

NonEmptyString = Annotated[str, Field(min_length=1)]


class ComponentVersions(ContractModel):
    """Optional publication-relevant component version metadata."""

    extractor_version: str | None = None
    normalizer_version: str | None = None
    profile_builder_version: str | None = None
    validator_version: str | None = None


class StoredProject(ContractModel):
    """One validated immutable project publication record."""

    project_id: NonEmptyString
    request_id: NonEmptyString
    project_profile: ProjectProfile
    validation_result: ValidationResult
    taxonomy_version: NonEmptyString
    extractor_version: str | None = None
    normalizer_version: str | None = None
    profile_builder_version: str | None = None
    validator_version: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Reject naive times and normalize persisted timestamps to UTC."""
        if value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_stored_project(self) -> Self:
        """Require matching identity, valid validation, and an aware timestamp."""
        if self.request_id != self.project_profile.request_id:
            raise ValueError("request_id must match project profile")
        if not self.validation_result.valid:
            raise ValueError("stored project requires valid validation")
        return self


class PublicationStatus(str, Enum):
    """Outcome of one guarded publication attempt."""

    PUBLISHED = "published"
    ALREADY_PUBLISHED = "already_published"
    REJECTED = "rejected"
    FAILED = "failed"


class PublicationErrorCode(str, Enum):
    """Stable publication business and infrastructure error codes."""

    PROFILE_MISSING = "PROFILE_MISSING"
    VALIDATION_MISSING = "VALIDATION_MISSING"
    PROFILE_INVALID = "PROFILE_INVALID"
    BLOCKING_ISSUES_PRESENT = "BLOCKING_ISSUES_PRESENT"
    UNRESOLVED_REQUIREMENTS_PRESENT = "UNRESOLVED_REQUIREMENTS_PRESENT"
    PENDING_CLARIFICATION = "PENDING_CLARIFICATION"
    ACTIVE_ESCALATION = "ACTIVE_ESCALATION"
    REQUEST_ID_MISMATCH = "REQUEST_ID_MISMATCH"
    INVALID_PUBLICATION_STATE = "INVALID_PUBLICATION_STATE"
    TAXONOMY_VERSION_MISSING = "TAXONOMY_VERSION_MISSING"
    REPOSITORY_FAILURE = "REPOSITORY_FAILURE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class PublicationResult(ContractModel):
    """Structured publication output and optional completed state."""

    request_id: NonEmptyString
    status: PublicationStatus
    changed: bool
    stored_project: StoredProject | None = None
    updated_state: CatalogAgentState | None = None
    message: NonEmptyString
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """Keep persistence and completion claims internally consistent."""
        if self.status in {
            PublicationStatus.PUBLISHED,
            PublicationStatus.ALREADY_PUBLISHED,
        }:
            expected_changed = self.status is PublicationStatus.PUBLISHED
            if (
                self.changed is not expected_changed
                or self.stored_project is None
                or self.updated_state is None
                or self.updated_state.status is not CatalogStatus.COMPLETED
                or self.updated_state.stage is not CatalogStage.COMPLETED
                or self.error_code is not None
            ):
                raise ValueError("successful publication result is inconsistent")
        elif (
            self.changed
            or self.stored_project is not None
            or self.updated_state is not None
            or not self.error_code
        ):
            raise ValueError("unsuccessful publication cannot return stored state")
        return self


class PublicationGuardResult(ContractModel):
    """Ordinary publication eligibility decision."""

    publishable: bool
    error_code: str | None = None
    message: NonEmptyString

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """Require an error only for non-publishable input."""
        if self.publishable == (self.error_code is not None):
            raise ValueError("guard result error does not match publishability")
        return self
