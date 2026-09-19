"""Tests for clarification contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import AnswerType, ClarificationQuestion


def test_single_choice_with_two_options_is_accepted() -> None:
    question = ClarificationQuestion(
        question_id="framework",
        field="requirements",
        question="Which framework is required?",
        answer_type=AnswerType.SINGLE_CHOICE,
        options=["Django", "Flask"],
    )

    assert question.options == ["Django", "Flask"]


@pytest.mark.parametrize("options", [[], ["Django"], ["Django", "   "]])
def test_single_choice_without_two_non_blank_options_is_rejected(
    options: list[str],
) -> None:
    with pytest.raises(ValidationError):
        ClarificationQuestion(
            question_id="framework",
            field="requirements",
            question="Which framework is required?",
            answer_type=AnswerType.SINGLE_CHOICE,
            options=options,
        )


def test_free_text_question_with_options_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClarificationQuestion(
            question_id="framework",
            field="requirements",
            question="Which framework is required?",
            answer_type=AnswerType.FREE_TEXT,
            options=["Django", "Flask"],
        )


def test_clarification_list_defaults_are_not_shared() -> None:
    first = ClarificationQuestion(
        question_id="first",
        field="requirements",
        question="Describe the requirement.",
        answer_type=AnswerType.FREE_TEXT,
    )
    second = ClarificationQuestion(
        question_id="second",
        field="requirements",
        question="Describe another requirement.",
        answer_type=AnswerType.FREE_TEXT,
    )

    first.options.append("Unexpected later mutation")

    assert second.options == []
