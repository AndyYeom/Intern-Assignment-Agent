"""Serializable contracts for bounded LangGraph orchestration."""

from enum import Enum
from typing import Annotated, Self, TypedDict

from pydantic import Field, model_validator

from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogDecision,
    CatalogStatus,
    ClarificationRequest,
    ContractModel,
    EscalationRequest,
)
from project_catalog_agent.persistence import PublicationResult

NonEmptyString = Annotated[str, Field(min_length=1)]


class WorkflowError(ContractModel):
    """Safe workflow-level failure information suitable for checkpoints."""

    code: NonEmptyString
    message: NonEmptyString
    node: NonEmptyString
    retryable: bool


class CatalogWorkflowState(TypedDict):
    """Small orchestration state whose sole domain authority is catalog_state."""

    catalog_state: CatalogAgentState
    last_decision: CatalogDecision | None
    last_publication_result: PublicationResult | None
    transition_count: int
    workflow_error: WorkflowError | None


class WorkflowOutcome(str, Enum):
    """Application-facing terminal or paused workflow outcomes."""

    COMPLETED = "completed"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    ESCALATED = "escalated"
    PERMANENT_FAILURE = "permanent_failure"


class CatalogWorkflowResult(ContractModel):
    """Facade result that hides LangGraph checkpoint and interrupt details."""

    request_id: NonEmptyString
    thread_id: NonEmptyString
    outcome: WorkflowOutcome
    catalog_state: CatalogAgentState
    pending_clarification: ClarificationRequest | None = None
    escalation: EscalationRequest | None = None
    stored_project_id: str | None = None
    error: WorkflowError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Keep the public outcome aligned with the authoritative domain state."""
        if self.outcome is WorkflowOutcome.COMPLETED:
            if (
                self.catalog_state.status is not CatalogStatus.COMPLETED
                or not self.stored_project_id
                or self.pending_clarification is not None
                or self.escalation is not None
            ):
                raise ValueError("completed workflow result is inconsistent")
        elif self.outcome is WorkflowOutcome.AWAITING_CLARIFICATION:
            if (
                self.catalog_state.status is not CatalogStatus.AWAITING_CLARIFICATION
                or self.pending_clarification is None
            ):
                raise ValueError("clarification workflow result is inconsistent")
        elif self.outcome is WorkflowOutcome.ESCALATED:
            if (
                self.catalog_state.status is not CatalogStatus.ESCALATED
                or self.escalation is None
            ):
                raise ValueError("escalated workflow result is inconsistent")
        elif self.error is None and not self.catalog_state.errors:
            raise ValueError("permanent failure requires a safe explanation")
        return self


class CatalogWorkflowConfig(ContractModel):
    """Final workflow safety configuration."""

    max_transitions: Annotated[int, Field(ge=1)] = 30
