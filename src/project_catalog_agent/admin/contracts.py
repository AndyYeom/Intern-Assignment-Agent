"""Safe contracts for terminal administration operations."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from project_catalog_agent.admin.roles import AdminRole
from project_catalog_agent.catalog.contracts.common import ContractModel
from project_catalog_agent.catalog.contracts.state import CatalogAgentState

NonEmptyString = Annotated[str, Field(min_length=1)]


class AuthenticationStatus(str, Enum):
    """Outcome of one authentication operation."""

    AUTHENTICATED = "authenticated"
    REJECTED = "rejected"


class AuthenticationResult(ContractModel):
    """Credential-free result returned by the authentication service."""

    status: AuthenticationStatus
    actor_id: str | None = None
    role: AdminRole | None = None
    error_code: str | None = None
    message: NonEmptyString

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """Ensure successful and rejected results cannot be confused."""
        if self.status is AuthenticationStatus.AUTHENTICATED:
            if (
                self.actor_id is None
                or self.role is None
                or self.error_code is not None
            ):
                raise ValueError("authenticated result requires actor and role")
        elif self.actor_id is not None or self.role is not None or not self.error_code:
            raise ValueError("rejected result requires only an error code")
        return self


class EscalationDecision(str, Enum):
    """Bounded decisions available to an escalation reviewer."""

    ACKNOWLEDGE = "acknowledge"
    REJECT = "reject"
    CANCEL = "cancel"


class EscalationReviewResponse(ContractModel):
    """One authenticated, bounded review of a current escalation."""

    request_id: NonEmptyString
    escalation_id: NonEmptyString
    reviewed_by: NonEmptyString
    decision: EscalationDecision
    review_note: Annotated[str, Field(max_length=1_000)] | None = None
    submitted_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        """Require an auditable timezone-aware submission time."""
        if self.submitted_at.utcoffset() is None:
            raise ValueError("submitted_at must be timezone-aware")
        return self


class EscalationReviewStatus(str, Enum):
    """Outcome of applying an escalation review."""

    APPLIED = "applied"
    REJECTED = "rejected"


class EscalationReviewResult(ContractModel):
    """Immutable state update or stable rejection for an escalation review."""

    request_id: NonEmptyString
    escalation_id: NonEmptyString
    status: EscalationReviewStatus
    changed: bool
    updated_state: CatalogAgentState | None = None
    message: NonEmptyString
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """Keep applied and rejected result payloads consistent."""
        if self.status is EscalationReviewStatus.APPLIED:
            if not self.changed or self.updated_state is None or self.error_code:
                raise ValueError("applied review requires an updated state")
        elif self.changed or self.updated_state is not None or not self.error_code:
            raise ValueError("rejected review requires only an error code")
        return self


class AdminAuditEvent(ContractModel):
    """Credential-free audit event for an authenticated business operation."""

    event_id: NonEmptyString
    actor_id: NonEmptyString
    role: AdminRole
    operation: NonEmptyString
    request_id: NonEmptyString
    target_id: NonEmptyString
    outcome: Literal["succeeded", "rejected", "cancelled"]
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        """Require timezone-aware audit timestamps."""
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return self
