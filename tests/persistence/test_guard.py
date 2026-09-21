"""Tests for deterministic publication eligibility rules."""

from datetime import UTC, datetime

import pytest

from project_catalog_agent.catalog.contracts import (
    CatalogStage,
    CatalogStatus,
    ClarificationRequest,
    EscalationRequest,
    IssueCategory,
    IssueSeverity,
    MappingStatus,
    UnresolvedProjectRequirement,
    ValidationIssue,
    ValidationResult,
)
from project_catalog_agent.persistence import ProjectPublicationGuard
from tests.persistence.helpers import valid_state


def guard(version: str = "0.1") -> ProjectPublicationGuard:
    return ProjectPublicationGuard(lambda: version)


def test_valid_profile_passes_without_mutation() -> None:
    state = valid_state()
    before = state.model_dump_json()

    result = guard().evaluate(state)

    assert result.publishable
    assert result.error_code is None
    assert state.model_dump_json() == before


@pytest.mark.parametrize(
    ("updates", "error_code"),
    [
        ({"candidate_profile": None}, "PROFILE_MISSING"),
        ({"validation_result": None}, "VALIDATION_MISSING"),
        (
            {"validation_result": ValidationResult(valid=False, issues=[])},
            "PROFILE_INVALID",
        ),
    ],
)
def test_missing_or_invalid_artifacts_are_rejected(
    updates: dict[str, object], error_code: str
) -> None:
    state = valid_state().model_copy(update=updates, deep=True)

    result = guard().evaluate(state)

    assert not result.publishable
    assert result.error_code == error_code


def test_blocking_issue_is_rejected_even_in_malformed_valid_result() -> None:
    issue = ValidationIssue(
        code="BLOCKING",
        field="requirements[0]",
        severity=IssueSeverity.BLOCKING,
        category=IssueCategory.CONFLICT,
        message="Controlled blocking issue.",
    )
    malformed = ValidationResult.model_construct(valid=True, issues=[issue])
    state = valid_state().model_copy(update={"validation_result": malformed}, deep=True)

    result = guard().evaluate(state)

    assert result.error_code == "BLOCKING_ISSUES_PRESENT"


def test_warning_only_valid_validation_is_publishable() -> None:
    warning = ValidationIssue(
        code="WARNING",
        field="requirements[0].confidence",
        severity=IssueSeverity.WARNING,
        category=IssueCategory.AMBIGUITY,
        message="Controlled warning.",
    )
    state = valid_state().model_copy(
        update={"validation_result": ValidationResult(valid=True, issues=[warning])},
        deep=True,
    )

    assert guard().evaluate(state).publishable


def test_pending_clarification_is_rejected_first() -> None:
    state = valid_state().model_copy(
        update={
            "status": CatalogStatus.AWAITING_CLARIFICATION,
            "stage": CatalogStage.AWAITING_CLARIFICATION,
            "pending_clarification": ClarificationRequest(
                clarification_id="clarification-1",
                request_id="STATE-001",
                issue_code="CONTROLLED",
                field="requirements[0]",
                question="Controlled question?",
            ),
        },
        deep=True,
    )

    assert guard().evaluate(state).error_code == "PENDING_CLARIFICATION"


def test_active_escalation_is_rejected() -> None:
    state = valid_state().model_copy(
        update={
            "status": CatalogStatus.ESCALATED,
            "stage": CatalogStage.ESCALATED,
            "escalation": EscalationRequest(
                escalation_id="escalation-1",
                request_id="STATE-001",
                issue_code="CONTROLLED",
                field="requirements[0]",
                reason="Controlled escalation.",
                context_summary="Controlled context.",
                recommended_review="Review safely.",
            ),
        },
        deep=True,
    )

    assert guard().evaluate(state).error_code == "ACTIVE_ESCALATION"


def test_mismatched_profile_request_id_is_rejected() -> None:
    state = valid_state()
    assert state.candidate_profile is not None
    profile = state.candidate_profile.model_copy(
        update={"request_id": "OTHER"}, deep=True
    )
    malformed = state.model_copy(update={"candidate_profile": profile}, deep=True)

    assert guard().evaluate(malformed).error_code == "REQUEST_ID_MISMATCH"


@pytest.mark.parametrize("field", ["unresolved_requirements", "unresolved_skills"])
def test_unresolved_content_is_rejected(field: str) -> None:
    state = valid_state()
    assert state.candidate_profile is not None
    update: dict[str, object]
    if field == "unresolved_requirements":
        update = {
            field: [
                UnresolvedProjectRequirement(
                    source_requirement_index=1,
                    raw_skill="Unknown",
                    mapping_status=MappingStatus.UNMAPPED,
                    importance="preferred",
                    required_level=1,
                    evidence_text="Unknown evidence.",
                )
            ]
        }
    else:
        update = {field: ["Unknown"]}
    profile = state.candidate_profile.model_copy(update=update, deep=True)
    malformed = state.model_copy(update={"candidate_profile": profile}, deep=True)

    assert guard().evaluate(malformed).error_code == "UNRESOLVED_REQUIREMENTS_PRESENT"


def test_missing_taxonomy_version_and_invalid_stage_are_rejected() -> None:
    assert guard("").evaluate(valid_state()).error_code == "TAXONOMY_VERSION_MISSING"
    invalid_stage = valid_state().model_copy(
        update={"stage": CatalogStage.PROFILE_BUILT}, deep=True
    )
    assert guard().evaluate(invalid_stage).error_code == "INVALID_PUBLICATION_STATE"


def test_stored_project_requires_aware_time() -> None:
    state = valid_state()
    assert state.candidate_profile is not None
    assert state.validation_result is not None
    with pytest.raises(ValueError):
        from project_catalog_agent.persistence import StoredProject

        StoredProject(
            project_id="PRJ-X",
            request_id=state.request.request_id,
            project_profile=state.candidate_profile,
            validation_result=state.validation_result,
            taxonomy_version="0.1",
            created_at=datetime(2026, 1, 1),
        )

    assert datetime.now(UTC).utcoffset() is not None
