"""Serializable contracts for one catalog-agent request state."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from project_catalog_agent.catalog.contracts.common import ContractModel
from project_catalog_agent.catalog.contracts.extraction import (
    RequirementExtractionResult,
)
from project_catalog_agent.catalog.contracts.profile import ProjectProfile
from project_catalog_agent.catalog.contracts.recovery import (
    ClarificationRequest,
    EscalationRequest,
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryStatus,
)
from project_catalog_agent.catalog.contracts.request import CreateProjectRequest
from project_catalog_agent.catalog.contracts.taxonomy import (
    TaxonomyNormalizationResult,
)
from project_catalog_agent.catalog.contracts.validation import ValidationResult

NonEmptyString = Annotated[str, Field(min_length=1)]


class CatalogStatus(str, Enum):
    """Overall processing condition for one catalog request."""

    RECEIVED = "received"
    PROCESSING = "processing"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    COMPLETED = "completed"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    ESCALATED = "escalated"


class CatalogStage(str, Enum):
    """Current valid pipeline artifact or paused workflow position."""

    RECEIVED = "received"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    PROFILE_BUILT = "profile_built"
    VALIDATED = "validated"
    RECOVERY = "recovery"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    ESCALATED = "escalated"
    COMPLETED = "completed"


class AgentError(ContractModel):
    """Stable, serializable operational error information."""

    code: NonEmptyString
    message: NonEmptyString
    stage: CatalogStage
    retryable: bool
    action: RecoveryActionName | None = None
    issue_code: str | None = None
    field: str | None = None


class RecoveryHistoryEntry(ContractModel):
    """Compact summary of one applied recovery result."""

    sequence: Annotated[int, Field(ge=1)]
    action_request: RecoveryActionRequest
    status: RecoveryStatus
    changed: bool
    error_code: str | None = None
    message: NonEmptyString
    produced_extraction_result: bool = False
    produced_normalization_result: bool = False
    produced_candidate_profile: bool = False
    produced_clarification_request: bool = False
    produced_escalation: bool = False


class ClarificationHistoryEntry(ContractModel):
    """Compact audit record for one accepted admin clarification."""

    sequence: Annotated[int, Field(ge=1)]
    clarification_id: NonEmptyString
    issue_code: NonEmptyString
    field: NonEmptyString
    answered_by: NonEmptyString
    answer_type: Literal["selected_value", "free_text"]
    accepted_value: NonEmptyString
    submitted_at: datetime
    applied_stage: CatalogStage


class EscalationReviewHistoryEntry(ContractModel):
    """Compact record of one authenticated escalation review."""

    sequence: Annotated[int, Field(ge=1)]
    request_id: NonEmptyString
    escalation_id: NonEmptyString
    reviewed_by: NonEmptyString
    decision: Literal["acknowledge", "reject", "cancel"]
    review_note: Annotated[str, Field(max_length=1_000)] | None = None
    submitted_at: datetime


class CatalogAgentState(ContractModel):
    """Complete current state for one project-catalog request."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=True,
    )

    request: CreateProjectRequest
    status: CatalogStatus = CatalogStatus.RECEIVED
    stage: CatalogStage = CatalogStage.RECEIVED
    extraction_result: RequirementExtractionResult | None = None
    normalization_result: TaxonomyNormalizationResult | None = None
    candidate_profile: ProjectProfile | None = None
    validation_result: ValidationResult | None = None
    pending_clarification: ClarificationRequest | None = None
    escalation: EscalationRequest | None = None
    recovery_history: list[RecoveryHistoryEntry] = Field(default_factory=list)
    clarification_history: list[ClarificationHistoryEntry] = Field(default_factory=list)
    escalation_review_history: list[EscalationReviewHistoryEntry] = Field(
        default_factory=list
    )
    retry_counts: dict[RecoveryActionName, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict
    )
    errors: list[AgentError] = Field(default_factory=list)
    published_project_id: NonEmptyString | None = None
    state_version: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def validate_state_invariants(self) -> Self:
        """Reject impossible artifact, identity, and workflow combinations."""
        if self.normalization_result is not None and self.extraction_result is None:
            raise ValueError("normalization_result requires extraction_result")
        if self.candidate_profile is not None and (
            self.extraction_result is None or self.normalization_result is None
        ):
            raise ValueError(
                "candidate_profile requires extraction and normalization results"
            )
        if self.validation_result is not None and self.candidate_profile is None:
            raise ValueError("validation_result requires candidate_profile")

        request_id = self.request.request_id
        if (
            self.candidate_profile is not None
            and self.candidate_profile.request_id != request_id
        ):
            raise ValueError("candidate_profile request_id does not match state")
        if (
            self.pending_clarification is not None
            and self.pending_clarification.request_id != request_id
        ):
            raise ValueError("clarification request_id does not match state")
        if self.escalation is not None and self.escalation.request_id != request_id:
            raise ValueError("escalation request_id does not match state")
        for expected_sequence, recovery_entry in enumerate(
            self.recovery_history, start=1
        ):
            if recovery_entry.sequence != expected_sequence:
                raise ValueError("recovery history sequence is not monotonic")
            if recovery_entry.action_request.request_id != request_id:
                raise ValueError("recovery history request_id does not match state")
        for expected_sequence, clarification_entry in enumerate(
            self.clarification_history, start=1
        ):
            if clarification_entry.sequence != expected_sequence:
                raise ValueError("clarification history sequence is not monotonic")
            if clarification_entry.submitted_at.utcoffset() is None:
                raise ValueError("clarification history time must be timezone-aware")
        for expected_sequence, review_entry in enumerate(
            self.escalation_review_history, start=1
        ):
            if review_entry.sequence != expected_sequence:
                raise ValueError("escalation review history sequence is not monotonic")
            if review_entry.request_id != request_id:
                raise ValueError("escalation review request_id does not match state")
            if review_entry.submitted_at.utcoffset() is None:
                raise ValueError("escalation review time must be timezone-aware")

        if self.pending_clarification is not None and self.escalation is not None:
            raise ValueError("clarification and escalation cannot coexist")
        if self.status is CatalogStatus.AWAITING_CLARIFICATION and (
            self.pending_clarification is None
            or self.stage is not CatalogStage.AWAITING_CLARIFICATION
        ):
            raise ValueError(
                "awaiting_clarification requires matching stage and payload"
            )
        if self.pending_clarification is not None and (
            self.status is not CatalogStatus.AWAITING_CLARIFICATION
            or self.stage is not CatalogStage.AWAITING_CLARIFICATION
        ):
            raise ValueError("pending clarification requires awaiting state")
        if self.stage is CatalogStage.AWAITING_CLARIFICATION and (
            self.status is not CatalogStatus.AWAITING_CLARIFICATION
            or self.pending_clarification is None
        ):
            raise ValueError("awaiting stage requires clarification state")
        if self.status is CatalogStatus.ESCALATED and (
            self.escalation is None or self.stage is not CatalogStage.ESCALATED
        ):
            raise ValueError("escalated status requires matching stage and payload")
        if self.escalation is not None and (
            self.status is not CatalogStatus.ESCALATED
            or self.stage is not CatalogStage.ESCALATED
        ):
            raise ValueError("escalation payload requires escalated state")
        if self.stage is CatalogStage.ESCALATED and (
            self.status is not CatalogStatus.ESCALATED or self.escalation is None
        ):
            raise ValueError("escalated stage requires escalation state")
        if self.status is CatalogStatus.COMPLETED and (
            self.validation_result is None
            or not self.validation_result.valid
            or self.stage is not CatalogStage.COMPLETED
            or self.published_project_id is None
        ):
            raise ValueError(
                "completed state requires publication and valid validation"
            )
        if self.published_project_id is not None and (
            self.status is not CatalogStatus.COMPLETED
            or self.stage is not CatalogStage.COMPLETED
        ):
            raise ValueError("published project ID requires completed state")
        if (
            self.validation_result is not None
            and not self.validation_result.valid
            and self.status is CatalogStatus.COMPLETED
        ):
            raise ValueError("invalid validation cannot be completed")
        if (
            self.stage is CatalogStage.COMPLETED
            and self.status is not CatalogStatus.COMPLETED
        ):
            raise ValueError("completed stage requires completed status")
        return self


def create_initial_catalog_state(
    request: CreateProjectRequest,
) -> CatalogAgentState:
    """Create version one without retaining a mutable request reference."""
    return CatalogAgentState(request=request.model_copy(deep=True))
