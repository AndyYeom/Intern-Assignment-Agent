"""Clarification question and answer contracts."""

from typing import Self

from pydantic import Field, model_validator

from project_catalog_agent.catalog.contracts.common import AnswerType, ContractModel


class ClarificationQuestion(ContractModel):
    """A question requesting missing or ambiguous project information."""

    question_id: str
    field: str
    question: str
    answer_type: AnswerType
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_options(self) -> Self:
        """Ensure options are appropriate for the configured answer type."""
        if self.answer_type is AnswerType.SINGLE_CHOICE:
            if len(self.options) < 2 or any(not option for option in self.options):
                msg = "single-choice questions require at least two non-blank options"
                raise ValueError(msg)
        elif self.options:
            msg = "only single-choice questions may define options"
            raise ValueError(msg)
        return self


class ClarificationAnswer(ContractModel):
    """An answer supplied for a clarification question."""

    question_id: str
    answer: str | int
