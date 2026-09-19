"""Contracts for explicit, bounded catalog recovery actions."""

import re
from enum import Enum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, JsonValue, model_validator

from project_catalog_agent.catalog.contracts.common import ContractModel
from project_catalog_agent.catalog.contracts.extraction import (
    RequirementExtractionResult,
)
from project_catalog_agent.catalog.contracts.profile import ProjectProfile
from project_catalog_agent.catalog.contracts.request import CreateProjectRequest
from project_catalog_agent.catalog.contracts.taxonomy import (
    TaxonomyNormalizationResult,
)
from project_catalog_agent.catalog.contracts.validation import ValidationResult

NonEmptyString = Annotated[str, Field(min_length=1)]
_REQUIREMENT_PATH = re.compile(r"^requirements\[(\d+)](?:\.|$)")
_PROVENANCE_PATH = re.compile(r"^requirements\[(\d+)]\.provenance\[(\d+)](?:\.|$)")
_UNRESOLVED_PATH = re.compile(r"^unresolved_requirements\[(\d+)](?:\.|$)")


class RecoveryActionName(str, Enum):
    """Fixed action names accepted by the recovery boundary."""

    REBUILD_PROFILE = "rebuild_profile"
    REEXTRACT_FIELD = "reextract_field"
    LOOKUP_TAXONOMY = "lookup_taxonomy"
    RECONSIDER_MAPPING = "reconsider_mapping"
    REQUEST_CLARIFICATION = "request_clarification"
    ESCALATE = "escalate"


class RecoveryStatus(str, Enum):
    """Outcome of one bounded recovery action execution."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AWAITING_INPUT = "awaiting_input"
    ESCALATED = "escalated"
    NO_CHANGE = "no_change"


class RecoveryActionRequest(ContractModel):
    """An explicit request to execute one action for one validation issue."""

    request_id: NonEmptyString
    action: RecoveryActionName
    issue_code: NonEmptyString
    issue_field: NonEmptyString
    attempt_number: Annotated[int, Field(ge=1)] = 1
    target_requirement_index: Annotated[int, Field(ge=0)] | None = None
    target_provenance_index: Annotated[int, Field(ge=0)] | None = None
    target_unresolved_index: Annotated[int, Field(ge=0)] | None = None
    context: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reconcile_field_path_indexes(self) -> Self:
        """Populate known indexes and reject contradictory explicit targets."""
        allowed_context_keys = {
            "preferred_candidate_skill_id",
            "rejected_candidate_skill_ids",
        }
        if set(self.context) - allowed_context_keys:
            msg = "context contains an unsupported recovery hint"
            raise ValueError(msg)
        if self.context and self.action is not RecoveryActionName.RECONSIDER_MAPPING:
            msg = "structured mapping hints require reconsider_mapping"
            raise ValueError(msg)
        provenance_match = _PROVENANCE_PATH.match(self.issue_field)
        requirement_match = _REQUIREMENT_PATH.match(self.issue_field)
        unresolved_match = _UNRESOLVED_PATH.match(self.issue_field)
        parsed_requirement = (
            int(provenance_match.group(1))
            if provenance_match is not None
            else (
                int(requirement_match.group(1))
                if requirement_match is not None
                else None
            )
        )
        parsed_provenance = (
            int(provenance_match.group(2)) if provenance_match is not None else None
        )
        parsed_unresolved = (
            int(unresolved_match.group(1)) if unresolved_match is not None else None
        )
        self._reconcile_index(
            "target_requirement_index",
            self.target_requirement_index,
            parsed_requirement,
        )
        self._reconcile_index(
            "target_provenance_index",
            self.target_provenance_index,
            parsed_provenance,
        )
        self._reconcile_index(
            "target_unresolved_index",
            self.target_unresolved_index,
            parsed_unresolved,
        )
        if parsed_requirement is not None and self.target_unresolved_index is not None:
            msg = "unresolved target contradicts requirement issue_field"
            raise ValueError(msg)
        if parsed_unresolved is not None and (
            self.target_requirement_index is not None
            or self.target_provenance_index is not None
        ):
            msg = "requirement target contradicts unresolved issue_field"
            raise ValueError(msg)
        if (
            self.target_provenance_index is not None
            and self.target_requirement_index is None
        ):
            msg = "target_provenance_index requires target_requirement_index"
            raise ValueError(msg)
        return self

    def _reconcile_index(
        self,
        field_name: str,
        explicit_value: int | None,
        parsed_value: int | None,
    ) -> None:
        if (
            explicit_value is not None
            and parsed_value is not None
            and explicit_value != parsed_value
        ):
            msg = f"{field_name} contradicts issue_field"
            raise ValueError(msg)
        if explicit_value is None and parsed_value is not None:
            object.__setattr__(self, field_name, parsed_value)


class RecoveryContext(ContractModel):
    """Current validated artifacts available to recovery actions."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=True,
    )

    request: CreateProjectRequest
    extraction_result: RequirementExtractionResult
    normalization_result: TaxonomyNormalizationResult
    candidate_profile: ProjectProfile
    validation_result: ValidationResult


class ClarificationOption(ContractModel):
    """One deterministic answer option for a clarification request."""

    value: NonEmptyString
    label: NonEmptyString
    skill_id: str | None = None


class ClarificationRequest(ContractModel):
    """A question prepared for later delivery by a clarification workflow."""

    clarification_id: NonEmptyString
    request_id: NonEmptyString
    issue_code: NonEmptyString
    field: NonEmptyString
    question: NonEmptyString
    related_raw_skill: str | None = None
    options: list[ClarificationOption] = Field(default_factory=list)
    allow_free_text: bool = True


class EscalationRequest(ContractModel):
    """A deterministic human-review escalation that has not been sent."""

    escalation_id: NonEmptyString
    request_id: NonEmptyString
    issue_code: NonEmptyString
    field: NonEmptyString
    reason: NonEmptyString
    context_summary: NonEmptyString
    recommended_review: NonEmptyString


class RecoveryActionResult(ContractModel):
    """Structured outcome from exactly one recovery action execution."""

    request_id: NonEmptyString
    action: RecoveryActionName
    issue_code: NonEmptyString
    status: RecoveryStatus
    changed: bool
    extraction_result: RequirementExtractionResult | None = None
    normalization_result: TaxonomyNormalizationResult | None = None
    candidate_profile: ProjectProfile | None = None
    clarification_request: ClarificationRequest | None = None
    escalation: EscalationRequest | None = None
    message: NonEmptyString
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> Self:
        """Ensure status, changed flag, and returned artifacts agree."""
        artifacts = (
            self.extraction_result,
            self.normalization_result,
            self.candidate_profile,
        )
        if self.status is RecoveryStatus.FAILED:
            if (
                self.changed
                or not self.error_code
                or any(item is not None for item in artifacts)
            ):
                msg = (
                    "failed recovery requires changed=False, error_code, and no "
                    "updated artifact"
                )
                raise ValueError(msg)
        elif self.error_code is not None:
            msg = "only failed recovery may contain error_code"
            raise ValueError(msg)

        if self.status is RecoveryStatus.SUCCEEDED:
            if not self.changed or not any(item is not None for item in artifacts):
                msg = "successful changed recovery requires an updated artifact"
                raise ValueError(msg)
        elif self.status is RecoveryStatus.NO_CHANGE and (
            self.changed or any(item is not None for item in artifacts)
        ):
            msg = "no-change recovery cannot return an updated artifact"
            raise ValueError(msg)

        if self.status is RecoveryStatus.AWAITING_INPUT:
            if (
                self.changed
                or self.clarification_request is None
                or any(item is not None for item in artifacts)
            ):
                msg = "awaiting-input recovery requires a clarification request"
                raise ValueError(msg)
        elif self.clarification_request is not None:
            msg = "clarification request requires awaiting-input status"
            raise ValueError(msg)

        if self.status is RecoveryStatus.ESCALATED:
            if (
                self.changed
                or self.escalation is None
                or any(item is not None for item in artifacts)
            ):
                msg = "escalated recovery requires an escalation"
                raise ValueError(msg)
        elif self.escalation is not None:
            msg = "escalation payload requires escalated status"
            raise ValueError(msg)
        return self
