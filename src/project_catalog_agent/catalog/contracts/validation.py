"""Project profile validation contracts."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from project_catalog_agent.catalog.contracts.common import (
    ContractModel,
    IssueCategory,
    IssueSeverity,
)

NonEmptyString = Annotated[str, Field(min_length=1)]


class ValidationIssue(ContractModel):
    """A structured issue found while validating a profile."""

    code: NonEmptyString
    field: NonEmptyString
    severity: IssueSeverity
    category: IssueCategory
    message: NonEmptyString
    resolvable_by: list[NonEmptyString] = Field(default_factory=list)


class ValidationResult(ContractModel):
    """Outcome of validating a project profile."""

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_blocking_issues_for_valid_result(self) -> Self:
        """Prevent a valid result from containing a blocking issue."""
        if self.valid and any(
            issue.severity is IssueSeverity.BLOCKING for issue in self.issues
        ):
            msg = "a valid result cannot contain blocking issues"
            raise ValueError(msg)
        return self
