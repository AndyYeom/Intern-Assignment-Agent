"""Contracts for applying verified admin clarification answers."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Self

from pydantic import Field, model_validator

from project_catalog_agent.catalog.contracts.common import ContractModel
from project_catalog_agent.catalog.contracts.state import CatalogAgentState

NonEmptyString = Annotated[str, Field(min_length=1)]


class ClarificationResponse(ContractModel):
    """One bounded answer to the currently pending clarification."""

    request_id: NonEmptyString
    clarification_id: NonEmptyString
    answered_by: NonEmptyString
    selected_value: str | None = None
    free_text: str | None = None
    submitted_at: datetime

    @model_validator(mode="after")
    def validate_answer_form(self) -> Self:
        selected = self.selected_value is not None and bool(self.selected_value)
        free = self.free_text is not None and bool(self.free_text)
        if selected == free:
            raise ValueError("exactly one answer form must be provided")
        if self.submitted_at.utcoffset() is None:
            raise ValueError("submitted_at must be timezone-aware")
        return self


class ClarificationApplicationStatus(str, Enum):
    """Outcome of applying an admin clarification answer."""

    APPLIED = "applied"
    REJECTED = "rejected"


class ClarificationRejectionCode(str, Enum):
    """Stable ordinary rejection codes."""

    NO_PENDING_CLARIFICATION = "NO_PENDING_CLARIFICATION"
    REQUEST_ID_MISMATCH = "REQUEST_ID_MISMATCH"
    CLARIFICATION_ID_MISMATCH = "CLARIFICATION_ID_MISMATCH"
    CLARIFICATION_ALREADY_APPLIED = "CLARIFICATION_ALREADY_APPLIED"
    UNAUTHORIZED_RESPONDENT = "UNAUTHORIZED_RESPONDENT"
    INVALID_ANSWER_FORM = "INVALID_ANSWER_FORM"
    INVALID_SELECTED_OPTION = "INVALID_SELECTED_OPTION"
    FREE_TEXT_NOT_ALLOWED = "FREE_TEXT_NOT_ALLOWED"
    INVALID_TARGET_FIELD = "INVALID_TARGET_FIELD"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    UNKNOWN_TAXONOMY_SKILL = "UNKNOWN_TAXONOMY_SKILL"
    UNSUPPORTED_CLARIFICATION = "UNSUPPORTED_CLARIFICATION"
    ANSWER_APPLICATION_FAILED = "ANSWER_APPLICATION_FAILED"
    EVIDENCE_NOT_VERBATIM = "EVIDENCE_NOT_VERBATIM"


class ClarificationApplicationResult(ContractModel):
    """Structured application result with an updated state only on success."""

    request_id: NonEmptyString
    clarification_id: NonEmptyString
    status: ClarificationApplicationStatus
    changed: bool
    updated_state: CatalogAgentState | None = None
    message: NonEmptyString
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        if self.status is ClarificationApplicationStatus.APPLIED:
            if (
                not self.changed
                or self.updated_state is None
                or self.error_code is not None
            ):
                raise ValueError("applied result requires changed state and no error")
        elif self.changed or self.updated_state is not None or not self.error_code:
            raise ValueError("rejected result requires unchanged state and error code")
        return self
