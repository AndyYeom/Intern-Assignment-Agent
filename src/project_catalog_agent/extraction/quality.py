"""Deterministic, non-mutating quality warnings for extraction results."""

import re
from enum import Enum

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    IssueCategory,
    IssueSeverity,
    RequirementExtractionResult,
    RequirementImportance,
    ValidationIssue,
)


class ExtractionQualityIssueCode(str, Enum):
    """Stable codes emitted by the extraction quality checker."""

    EVIDENCE_NOT_VERBATIM = "EVIDENCE_NOT_VERBATIM"
    RAW_SKILL_CONTAINS_LEVEL_MODIFIER = "RAW_SKILL_CONTAINS_LEVEL_MODIFIER"
    LEARNING_OPPORTUNITY_NOT_SUPPORTED = "LEARNING_OPPORTUNITY_NOT_SUPPORTED"
    POSSIBLE_REQUIREMENT_FRAGMENTATION = "POSSIBLE_REQUIREMENT_FRAGMENTATION"


_LEVEL_MODIFIER_PATTERN = re.compile(
    r"\b(?:advanced|basic|beginner|entry[- ]level|expert|intermediate|senior|strong)\b",
    flags=re.IGNORECASE,
)
_LEARNING_LANGUAGE_PATTERN = re.compile(
    r"\b(?:learn|learns|learned|learning|training|skill development)\b|"
    r"\bdevelop(?:s|ed|ing)?\s+(?:their\s+)?(?:skills?|proficiency|capabilit(?:y|ies))\b",
    flags=re.IGNORECASE,
)
_ACTION_PHRASE_PATTERN = re.compile(
    r"^(?:build|compare|create|debug|design|develop|explain|extend|identify|"
    r"implement|modify|optimize|profile)\b",
    flags=re.IGNORECASE,
)


class ExtractionQualityChecker:
    """Report deterministic extraction warnings without changing the result."""

    def check(
        self,
        request: CreateProjectRequest,
        result: RequirementExtractionResult,
    ) -> tuple[ValidationIssue, ...]:
        """Return warnings for suspicious evidence, labels, and fragmentation."""
        issues: list[ValidationIssue] = []
        action_phrase_indexes: list[int] = []

        for index, requirement in enumerate(result.requirements):
            field_prefix = f"requirements.{index}"
            if requirement.evidence_text not in request.project_description:
                issues.append(
                    self._warning(
                        code=ExtractionQualityIssueCode.EVIDENCE_NOT_VERBATIM,
                        field=f"{field_prefix}.evidence_text",
                        category=IssueCategory.INVALID_VALUE,
                        message=(
                            "Evidence text is not an exact excerpt from the project "
                            "description."
                        ),
                    )
                )

            if _LEVEL_MODIFIER_PATTERN.search(requirement.raw_skill):
                issues.append(
                    self._warning(
                        code=(
                            ExtractionQualityIssueCode.RAW_SKILL_CONTAINS_LEVEL_MODIFIER
                        ),
                        field=f"{field_prefix}.raw_skill",
                        category=IssueCategory.INVALID_VALUE,
                        message="Raw skill contains a proficiency modifier.",
                    )
                )

            if (
                requirement.importance is RequirementImportance.LEARNING_OPPORTUNITY
                and not _LEARNING_LANGUAGE_PATTERN.search(requirement.evidence_text)
            ):
                issues.append(
                    self._warning(
                        code=(
                            ExtractionQualityIssueCode.LEARNING_OPPORTUNITY_NOT_SUPPORTED
                        ),
                        field=f"{field_prefix}.importance",
                        category=IssueCategory.CONFLICT,
                        message=(
                            "Learning-opportunity importance lacks explicit learning "
                            "language in its evidence."
                        ),
                    )
                )

            if _ACTION_PHRASE_PATTERN.search(requirement.raw_skill):
                action_phrase_indexes.append(index)

        if len(action_phrase_indexes) >= 2:
            joined_indexes = ", ".join(str(index) for index in action_phrase_indexes)
            issues.append(
                self._warning(
                    code=ExtractionQualityIssueCode.POSSIBLE_REQUIREMENT_FRAGMENTATION,
                    field="requirements",
                    category=IssueCategory.AMBIGUITY,
                    message=(
                        "Multiple requirements look like action fragments rather than "
                        f"consolidated skills at indexes: {joined_indexes}."
                    ),
                )
            )

        return tuple(issues)

    @staticmethod
    def _warning(
        *,
        code: ExtractionQualityIssueCode,
        field: str,
        category: IssueCategory,
        message: str,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code.value,
            field=field,
            severity=IssueSeverity.WARNING,
            category=category,
            message=message,
        )
