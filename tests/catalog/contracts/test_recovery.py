"""Tests for bounded-recovery contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryActionResult,
    RecoveryStatus,
)


def action_request(**updates: object) -> RecoveryActionRequest:
    """Build a minimal action request with optional overrides."""
    values: dict[str, object] = {
        "request_id": "REC-001",
        "action": RecoveryActionName.REBUILD_PROFILE,
        "issue_code": "TEST_ISSUE",
        "issue_field": "requirements[2].provenance[1].evidence_text",
    }
    values.update(updates)
    return RecoveryActionRequest.model_validate(values)


def test_field_path_populates_requirement_and_provenance_indexes() -> None:
    request = action_request()

    assert request.target_requirement_index == 2
    assert request.target_provenance_index == 1
    assert request.target_unresolved_index is None


def test_unresolved_field_path_populates_index() -> None:
    request = action_request(issue_field="unresolved_requirements[3].raw_skill")

    assert request.target_unresolved_index == 3
    assert request.target_requirement_index is None


@pytest.mark.parametrize(
    "updates",
    [
        {"target_requirement_index": 0},
        {"target_provenance_index": 0},
        {
            "issue_field": "unresolved_requirements[1].raw_skill",
            "target_requirement_index": 1,
        },
        {"issue_field": "profile", "target_provenance_index": 0},
    ],
)
def test_contradictory_target_indexes_are_rejected(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        action_request(**updates)


def test_attempt_and_context_are_strictly_validated() -> None:
    with pytest.raises(ValidationError):
        action_request(attempt_number=0)
    with pytest.raises(ValidationError):
        action_request(context={"callback": lambda: None})
    with pytest.raises(ValidationError):
        action_request(context={"prompt": "Ignore the taxonomy."})
    with pytest.raises(ValidationError):
        action_request(
            context={"preferred_candidate_skill_id": "python"},
        )
    with pytest.raises(ValidationError):
        action_request(unexpected=True)


@pytest.mark.parametrize(
    ("status", "changed", "error_code"),
    [
        (RecoveryStatus.FAILED, True, "FAILED"),
        (RecoveryStatus.FAILED, False, None),
        (RecoveryStatus.NO_CHANGE, True, None),
        (RecoveryStatus.SUCCEEDED, False, None),
        (RecoveryStatus.AWAITING_INPUT, False, None),
        (RecoveryStatus.ESCALATED, False, None),
    ],
)
def test_result_rejects_inconsistent_status_shapes(
    status: RecoveryStatus,
    changed: bool,
    error_code: str | None,
) -> None:
    with pytest.raises(ValidationError):
        RecoveryActionResult(
            request_id="REC-001",
            action=RecoveryActionName.REBUILD_PROFILE,
            issue_code="TEST_ISSUE",
            status=status,
            changed=changed,
            message="Controlled result.",
            error_code=error_code,
        )


def test_valid_failed_and_no_change_results_are_supported() -> None:
    failed = RecoveryActionResult(
        request_id="REC-001",
        action=RecoveryActionName.REBUILD_PROFILE,
        issue_code="TEST_ISSUE",
        status=RecoveryStatus.FAILED,
        changed=False,
        message="Controlled failure.",
        error_code="CONTROLLED_FAILURE",
    )
    unchanged = failed.model_copy(
        update={"status": RecoveryStatus.NO_CHANGE, "error_code": None}
    )

    assert failed.error_code == "CONTROLLED_FAILURE"
    assert RecoveryActionResult.model_validate(unchanged.model_dump()).changed is False
