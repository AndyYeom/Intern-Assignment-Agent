"""Tests for catalog result contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    AnswerType,
    CatalogResult,
    CatalogResultStatus,
    ClarificationQuestion,
    ProjectProfile,
)


def make_profile() -> ProjectProfile:
    """Build a minimal project profile."""
    return ProjectProfile(
        request_id="req-001",
        project_name="Recommendation Engine",
        project_description="Build a recommendation engine.",
        project_summary="A content recommendation project.",
    )


def make_question() -> ClarificationQuestion:
    """Build a clarification question."""
    return ClarificationQuestion(
        question_id="framework",
        field="requirements",
        question="Which framework is required?",
        answer_type=AnswerType.FREE_TEXT,
    )


def test_completed_result_with_profile_is_accepted() -> None:
    result = CatalogResult(
        request_id="req-001",
        status=CatalogResultStatus.COMPLETED,
        project_profile=make_profile(),
    )

    assert result.project_profile is not None
    assert result.project_id is None


def test_completed_result_without_profile_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CatalogResult(
            request_id="req-001",
            status=CatalogResultStatus.COMPLETED,
        )


def test_awaiting_clarification_without_questions_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CatalogResult(
            request_id="req-001",
            status=CatalogResultStatus.AWAITING_CLARIFICATION,
        )


def test_awaiting_clarification_with_question_is_accepted() -> None:
    result = CatalogResult(
        request_id="req-001",
        status=CatalogResultStatus.AWAITING_CLARIFICATION,
        clarification_questions=[make_question()],
    )

    assert len(result.clarification_questions) == 1


@pytest.mark.parametrize(
    "status",
    [CatalogResultStatus.ESCALATED, CatalogResultStatus.FAILED],
)
def test_error_status_without_message_is_rejected(
    status: CatalogResultStatus,
) -> None:
    with pytest.raises(ValidationError):
        CatalogResult(request_id="req-001", status=status)


def test_result_list_defaults_are_not_shared() -> None:
    first = CatalogResult(
        request_id="req-001",
        status=CatalogResultStatus.FAILED,
        message="First failure",
    )
    second = CatalogResult(
        request_id="req-002",
        status=CatalogResultStatus.FAILED,
        message="Second failure",
    )

    first.clarification_questions.append(make_question())

    assert second.clarification_questions == []
