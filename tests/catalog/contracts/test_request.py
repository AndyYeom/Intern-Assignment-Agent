"""Tests for project creation request contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import CreateProjectRequest


def test_valid_request() -> None:
    request = CreateProjectRequest(
        request_id="req-001",
        project_name="Recommendation Engine",
        project_description="Build a recommendation engine for course content.",
    )

    assert request.request_id == "req-001"


def test_request_strips_whitespace() -> None:
    request = CreateProjectRequest(
        request_id="  req-001  ",
        project_name="  Recommendation Engine  ",
        project_description="  Build the engine.  ",
    )

    assert request.request_id == "req-001"
    assert request.project_name == "Recommendation Engine"
    assert request.project_description == "Build the engine."


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "   "),
        ("project_name", "   "),
        ("project_description", "   "),
    ],
)
def test_blank_required_field_is_rejected(field: str, value: str) -> None:
    data = {
        "request_id": "req-001",
        "project_name": "Recommendation Engine",
        "project_description": "Build the engine.",
    }
    data[field] = value

    with pytest.raises(ValidationError):
        CreateProjectRequest.model_validate(data)


def test_unexpected_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateProjectRequest.model_validate(
            {
                "request_id": "req-001",
                "project_name": "Recommendation Engine",
                "project_description": "Build the engine.",
                "requested_operation": "create",
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "r" * 101),
        ("project_name", "p" * 201),
        ("project_description", "d" * 20_001),
    ],
)
def test_excessive_string_length_is_rejected(field: str, value: str) -> None:
    data = {
        "request_id": "req-001",
        "project_name": "Recommendation Engine",
        "project_description": "Build the engine.",
    }
    data[field] = value

    with pytest.raises(ValidationError):
        CreateProjectRequest.model_validate(data)
