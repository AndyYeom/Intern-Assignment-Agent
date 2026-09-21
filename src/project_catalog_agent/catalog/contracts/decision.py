"""Contracts for deterministic catalog next-step decisions."""

from enum import Enum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator

from project_catalog_agent.catalog.contracts.common import ContractModel
from project_catalog_agent.catalog.contracts.recovery import RecoveryActionRequest

NonEmptyString = Annotated[str, Field(min_length=1)]


class DecisionType(str, Enum):
    """One next step selected without executing it."""

    RUN_EXTRACTION = "run_extraction"
    RUN_NORMALIZATION = "run_normalization"
    BUILD_PROFILE = "build_profile"
    RUN_VALIDATION = "run_validation"
    PUBLISH_PROFILE = "publish_profile"
    EXECUTE_RECOVERY = "execute_recovery"
    WAIT_FOR_CLARIFICATION = "wait_for_clarification"
    COMPLETE = "complete"
    STOP_ESCALATED = "stop_escalated"
    STOP_PERMANENT_FAILURE = "stop_permanent_failure"


class DecisionReason(str, Enum):
    """Stable reason codes for policy output."""

    EXTRACTION_REQUIRED = "EXTRACTION_REQUIRED"
    NORMALIZATION_REQUIRED = "NORMALIZATION_REQUIRED"
    PROFILE_BUILD_REQUIRED = "PROFILE_BUILD_REQUIRED"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    PROFILE_VALID = "PROFILE_VALID"
    PROFILE_READY_TO_PUBLISH = "PROFILE_READY_TO_PUBLISH"
    PROFILE_PUBLISHED = "PROFILE_PUBLISHED"
    AUTOMATIC_RECOVERY_AVAILABLE = "AUTOMATIC_RECOVERY_AVAILABLE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    NO_PROGRESS_DETECTED = "NO_PROGRESS_DETECTED"
    RETRY_LIMIT_REACHED = "RETRY_LIMIT_REACHED"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    ALREADY_ESCALATED = "ALREADY_ESCALATED"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    NO_SAFE_ACTION = "NO_SAFE_ACTION"


class CatalogDecision(ContractModel):
    """Structured result from the pure decision policy."""

    decision_type: DecisionType
    reason_code: DecisionReason
    message: NonEmptyString
    action_request: RecoveryActionRequest | None = None
    selected_issue_code: str | None = None
    selected_issue_field: str | None = None

    @model_validator(mode="after")
    def validate_decision_shape(self) -> Self:
        """Keep recovery payloads and selected issue identity consistent."""
        executes = self.decision_type is DecisionType.EXECUTE_RECOVERY
        if executes != (self.action_request is not None):
            raise ValueError("execute_recovery requires exactly one action request")
        has_code = self.selected_issue_code is not None
        has_field = self.selected_issue_field is not None
        if has_code != has_field:
            raise ValueError("selected issue code and field must be provided together")
        if executes and not has_code:
            raise ValueError("recovery decisions require selected issue identity")
        return self


class CatalogDecisionPolicyConfig(ContractModel):
    """Immutable bounded retry configuration."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=True,
    )

    max_rebuild_attempts: Annotated[int, Field(ge=0)] = 1
    max_reextraction_attempts: Annotated[int, Field(ge=0)] = 2
    max_taxonomy_lookup_attempts: Annotated[int, Field(ge=0)] = 1
    max_mapping_reconsideration_attempts: Annotated[int, Field(ge=0)] = 1
    max_clarification_requests_per_issue: Annotated[int, Field(ge=0)] = 1
    max_total_recovery_attempts: Annotated[int, Field(ge=0)] = 5
    escalate_on_no_safe_action: bool = True
    escalate_after_no_change: bool = False
