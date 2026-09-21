"""Tests for validation result contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    IssueCategory,
    IssueSeverity,
    ValidationIssue,
    ValidationResult,
)


def make_issue(severity: IssueSeverity) -> ValidationIssue:
    """Build a validation issue with the requested severity."""
    return ValidationIssue(
        code="missing-skill",
        field="requirements",
        severity=severity,
        category=IssueCategory.MISSING_INFORMATION,
        message="At least one skill should be provided.",
    )


def test_valid_result_without_blocking_issues_is_accepted() -> None:
    result = ValidationResult(
        valid=True,
        issues=[make_issue(IssueSeverity.WARNING)],
    )

    assert result.valid is True


def test_valid_result_with_blocking_issue_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ValidationResult(
            valid=True,
            issues=[make_issue(IssueSeverity.BLOCKING)],
        )


def test_invalid_result_with_warning_only_issues_is_accepted() -> None:
    result = ValidationResult(
        valid=False,
        issues=[make_issue(IssueSeverity.WARNING)],
    )

    assert result.valid is False


def test_validation_list_defaults_are_not_shared() -> None:
    first = ValidationResult(valid=True)
    second = ValidationResult(valid=True)

    first.issues.append(make_issue(IssueSeverity.WARNING))

    assert second.issues == []
