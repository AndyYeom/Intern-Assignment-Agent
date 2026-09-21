"""Tests for admin clarification response and application contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    ClarificationApplicationResult,
    ClarificationApplicationStatus,
    ClarificationResponse,
)


def response_data() -> dict[str, object]:
    """Return one valid structured response payload."""
    return {
        "request_id": "CLR-001",
        "clarification_id": "clarification-001",
        "answered_by": "admin-1",
        "selected_value": "aws",
        "submitted_at": datetime(2026, 1, 1, tzinfo=UTC),
    }


@pytest.mark.parametrize(
    ("updates"),
    [
        {"selected_value": None},
        {"selected_value": "aws", "free_text": "AWS"},
        {"selected_value": "   "},
    ],
)
def test_response_requires_exactly_one_nonempty_answer(
    updates: dict[str, object],
) -> None:
    data = response_data()
    data.update(updates)

    with pytest.raises(ValidationError):
        ClarificationResponse.model_validate(data)


def test_response_requires_timezone_aware_timestamp() -> None:
    data = response_data()
    data["submitted_at"] = datetime(2026, 1, 1)

    with pytest.raises(ValidationError):
        ClarificationResponse.model_validate(data)


def test_response_strips_identifiers_and_round_trips() -> None:
    data = response_data()
    data["answered_by"] = " admin-1 "
    response = ClarificationResponse.model_validate(data)

    assert response.answered_by == "admin-1"
    assert (
        ClarificationResponse.model_validate_json(response.model_dump_json())
        == response
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": ClarificationApplicationStatus.APPLIED,
            "changed": False,
            "error_code": None,
        },
        {
            "status": ClarificationApplicationStatus.REJECTED,
            "changed": False,
            "error_code": None,
        },
    ],
)
def test_application_result_rejects_inconsistent_shapes(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ClarificationApplicationResult(
            request_id="CLR-001",
            clarification_id="clarification-001",
            message="Controlled result.",
            **payload,
        )
