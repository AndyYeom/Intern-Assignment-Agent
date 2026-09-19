"""Deterministic validation of candidate project profiles."""

from dataclasses import dataclass

from project_catalog_agent.catalog.contracts import (
    IssueCategory,
    IssueSeverity,
    MappingStatus,
    ProjectProfile,
    ProjectRequirement,
    RequirementImportance,
    UnresolvedProjectRequirement,
    ValidationIssue,
    ValidationResult,
)
from project_catalog_agent.profile.merge import (
    maximum_required_level,
    strongest_importance,
)
from project_catalog_agent.taxonomy import TaxonomyRepository


@dataclass(frozen=True, slots=True)
class ProfileValidationPolicy:
    """Immutable switches and thresholds for candidate-profile validation."""

    require_at_least_one_resolved_requirement: bool = True
    block_all_unresolved_requirements: bool = True
    low_confidence_threshold: float = 0.70
    warn_on_low_confidence: bool = True
    require_verbatim_evidence: bool = True
    require_provenance: bool = True

    def __post_init__(self) -> None:
        """Reject invalid confidence thresholds at configuration time."""
        if not 0.0 <= self.low_confidence_threshold <= 1.0:
            msg = "low_confidence_threshold must be between 0 and 1"
            raise ValueError(msg)


class ProjectProfileValidator:
    """Validate profile integrity and return every ordinary business issue."""

    def __init__(
        self,
        *,
        taxonomy_repository: TaxonomyRepository,
        policy: ProfileValidationPolicy | None = None,
    ) -> None:
        """Configure authoritative taxonomy lookup and validation policy."""
        self._taxonomy_repository = taxonomy_repository
        self._policy = policy or ProfileValidationPolicy()

    def validate(self, profile: ProjectProfile) -> ValidationResult:
        """Return all issues in deterministic category and source order."""
        profile_issues = self._profile_issues(profile)
        requirement_issues: list[ValidationIssue] = []
        provenance_issues: list[ValidationIssue] = []
        resolved_source_indexes: set[int] = set()

        for index, requirement in enumerate(profile.requirements):
            requirement_issues.extend(
                self._requirement_issues(profile, requirement, index)
            )
            current_provenance_issues, source_indexes = self._provenance_issues(
                profile,
                requirement,
                index,
            )
            provenance_issues.extend(current_provenance_issues)
            resolved_source_indexes.update(source_indexes)

        unresolved_issues = self._unresolved_issues(
            profile.unresolved_requirements,
            resolved_source_indexes,
        )
        issues = [
            *profile_issues,
            *requirement_issues,
            *provenance_issues,
            *unresolved_issues,
        ]
        valid = not any(issue.severity is IssueSeverity.BLOCKING for issue in issues)
        return ValidationResult(valid=valid, issues=issues)

    def _profile_issues(self, profile: ProjectProfile) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if (
            self._policy.require_at_least_one_resolved_requirement
            and not profile.requirements
        ):
            issues.append(
                _issue(
                    code="NO_RESOLVED_REQUIREMENTS",
                    field="requirements",
                    severity=IssueSeverity.BLOCKING,
                    category=IssueCategory.MISSING_INFORMATION,
                    message="The profile has no resolved project requirements.",
                    resolvable_by=[
                        "reextract_field",
                        "lookup_taxonomy",
                        "escalate",
                    ],
                )
            )

        seen_skill_ids: set[str] = set()
        reported_skill_ids: set[str] = set()
        for requirement in profile.requirements:
            if (
                requirement.skill_id in seen_skill_ids
                and requirement.skill_id not in reported_skill_ids
            ):
                issues.append(
                    _issue(
                        code="DUPLICATE_CANONICAL_SKILL",
                        field="requirements",
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.DUPLICATE,
                        message=(
                            "Canonical skill ID "
                            f"{requirement.skill_id!r} appears more than once."
                        ),
                        resolvable_by=["rebuild_profile"],
                    )
                )
                reported_skill_ids.add(requirement.skill_id)
            seen_skill_ids.add(requirement.skill_id)

        expected_unresolved = list(
            dict.fromkeys(
                requirement.raw_skill for requirement in profile.unresolved_requirements
            )
        )
        if profile.unresolved_skills != expected_unresolved:
            issues.append(
                _issue(
                    code="UNRESOLVED_LIST_MISMATCH",
                    field="unresolved_skills",
                    severity=IssueSeverity.BLOCKING,
                    category=IssueCategory.CONFLICT,
                    message=(
                        "unresolved_skills does not match structured unresolved "
                        "requirements."
                    ),
                    resolvable_by=["rebuild_profile"],
                )
            )
        return issues

    def _requirement_issues(
        self,
        profile: ProjectProfile,
        requirement: ProjectRequirement,
        index: int,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        prefix = f"requirements[{index}]"
        taxonomy_skill = self._taxonomy_repository.get_by_id(requirement.skill_id)
        if taxonomy_skill is None:
            issues.append(
                _issue(
                    code="UNKNOWN_SKILL_ID",
                    field=f"{prefix}.skill_id",
                    severity=IssueSeverity.BLOCKING,
                    category=IssueCategory.INVALID_VALUE,
                    message=f"Skill ID {requirement.skill_id!r} is not in the taxonomy.",
                    resolvable_by=["lookup_taxonomy", "rebuild_profile"],
                )
            )
        else:
            if requirement.canonical_name != taxonomy_skill.canonical_name:
                issues.append(
                    _issue(
                        code="CANONICAL_NAME_MISMATCH",
                        field=f"{prefix}.canonical_name",
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.CONFLICT,
                        message=(
                            f"Canonical name for {requirement.skill_id!r} does not "
                            "match the taxonomy."
                        ),
                        resolvable_by=["rebuild_profile"],
                    )
                )
            if not taxonomy_skill.active:
                issues.append(
                    _issue(
                        code="INACTIVE_SKILL",
                        field=f"{prefix}.skill_id",
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.INVALID_VALUE,
                        message=f"Skill ID {requirement.skill_id!r} is inactive.",
                        resolvable_by=["lookup_taxonomy", "reconsider_mapping"],
                    )
                )

        if (
            requirement.importance is RequirementImportance.HARD_REQUIREMENT
            and requirement.required_level is None
        ):
            issues.append(
                _issue(
                    code="MISSING_REQUIRED_LEVEL",
                    field=f"{prefix}.required_level",
                    severity=IssueSeverity.BLOCKING,
                    category=IssueCategory.MISSING_INFORMATION,
                    message="A hard requirement must define required_level.",
                    resolvable_by=["reextract_field", "request_clarification"],
                )
            )
        if self._policy.require_provenance and not requirement.provenance:
            issues.append(
                _issue(
                    code="EMPTY_PROVENANCE",
                    field=f"{prefix}.provenance",
                    severity=IssueSeverity.BLOCKING,
                    category=IssueCategory.MISSING_INFORMATION,
                    message="The resolved requirement has no source provenance.",
                    resolvable_by=["rebuild_profile"],
                )
            )
        source_indexes = [
            provenance.source_requirement_index for provenance in requirement.provenance
        ]
        if len(source_indexes) != len(set(source_indexes)):
            issues.append(
                _issue(
                    code="PROVENANCE_SKILL_INDEX_DUPLICATE",
                    field=f"{prefix}.provenance",
                    severity=IssueSeverity.BLOCKING,
                    category=IssueCategory.DUPLICATE,
                    message="A source requirement index appears more than once.",
                    resolvable_by=["rebuild_profile"],
                )
            )
        if (
            self._policy.warn_on_low_confidence
            and requirement.confidence < self._policy.low_confidence_threshold
        ):
            issues.append(
                _issue(
                    code="LOW_EXTRACTION_CONFIDENCE",
                    field=f"{prefix}.confidence",
                    severity=IssueSeverity.WARNING,
                    category=IssueCategory.AMBIGUITY,
                    message=(
                        "Extraction confidence is below the configured warning "
                        "threshold."
                    ),
                    resolvable_by=["reextract_field", "request_clarification"],
                )
            )
        if (
            self._policy.require_verbatim_evidence
            and requirement.evidence_text not in profile.project_description
        ):
            issues.append(
                _issue(
                    code="EVIDENCE_NOT_VERBATIM",
                    field=f"{prefix}.evidence_text",
                    severity=IssueSeverity.BLOCKING,
                    category=IssueCategory.CONFLICT,
                    message="Requirement evidence is not verbatim project text.",
                    resolvable_by=["reextract_field", "rebuild_profile"],
                )
            )

        if requirement.provenance:
            expected_importance = strongest_importance(
                item.importance for item in requirement.provenance
            )
            if requirement.importance is not expected_importance:
                issues.append(
                    _issue(
                        code="PROVENANCE_IMPORTANCE_CONFLICT",
                        field=f"{prefix}.importance",
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.CONFLICT,
                        message="Merged importance conflicts with provenance.",
                        resolvable_by=["rebuild_profile"],
                    )
                )
            expected_level = maximum_required_level(
                item.required_level for item in requirement.provenance
            )
            if requirement.required_level != expected_level:
                issues.append(
                    _issue(
                        code="PROVENANCE_LEVEL_CONFLICT",
                        field=f"{prefix}.required_level",
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.CONFLICT,
                        message="Merged required level conflicts with provenance.",
                        resolvable_by=["rebuild_profile"],
                    )
                )
        return issues

    def _provenance_issues(
        self,
        profile: ProjectProfile,
        requirement: ProjectRequirement,
        requirement_index: int,
    ) -> tuple[list[ValidationIssue], set[int]]:
        issues: list[ValidationIssue] = []
        source_indexes: set[int] = set()
        for provenance_index, provenance in enumerate(requirement.provenance):
            source_indexes.add(provenance.source_requirement_index)
            if (
                self._policy.require_verbatim_evidence
                and provenance.evidence_text not in profile.project_description
            ):
                issues.append(
                    _issue(
                        code="PROVENANCE_EVIDENCE_NOT_VERBATIM",
                        field=(
                            f"requirements[{requirement_index}].provenance"
                            f"[{provenance_index}].evidence_text"
                        ),
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.CONFLICT,
                        message="Provenance evidence is not verbatim project text.",
                        resolvable_by=["reextract_field", "rebuild_profile"],
                    )
                )
        return issues, source_indexes

    def _unresolved_issues(
        self,
        unresolved_requirements: list[UnresolvedProjectRequirement],
        resolved_source_indexes: set[int],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        seen_source_indexes: set[int] = set()
        ordered = sorted(
            enumerate(unresolved_requirements),
            key=lambda item: (item[1].source_requirement_index, item[0]),
        )
        unresolved_severity = (
            IssueSeverity.BLOCKING
            if self._policy.block_all_unresolved_requirements
            else IssueSeverity.WARNING
        )

        for original_index, requirement in ordered:
            prefix = f"unresolved_requirements[{original_index}]"
            if requirement.source_requirement_index in seen_source_indexes:
                issues.append(
                    _issue(
                        code="DUPLICATE_UNRESOLVED_SOURCE_INDEX",
                        field="unresolved_requirements",
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.DUPLICATE,
                        message="An unresolved source index appears more than once.",
                        resolvable_by=["rebuild_profile"],
                    )
                )
            seen_source_indexes.add(requirement.source_requirement_index)

            if requirement.source_requirement_index in resolved_source_indexes:
                issues.append(
                    _issue(
                        code="SOURCE_INDEX_COLLISION",
                        field=f"{prefix}.source_requirement_index",
                        severity=IssueSeverity.BLOCKING,
                        category=IssueCategory.CONFLICT,
                        message="A source index is both resolved and unresolved.",
                        resolvable_by=["rebuild_profile"],
                    )
                )

            if requirement.mapping_status is MappingStatus.UNMAPPED:
                issues.append(
                    _issue(
                        code="UNMAPPED_REQUIREMENT",
                        field=prefix,
                        severity=unresolved_severity,
                        category=IssueCategory.MISSING_INFORMATION,
                        message=f"{requirement.raw_skill!r} is not mapped.",
                        resolvable_by=[
                            "lookup_taxonomy",
                            "reextract_field",
                            "escalate",
                        ],
                    )
                )
            elif requirement.mapping_status is MappingStatus.NEEDS_REVIEW:
                issues.append(
                    _issue(
                        code="NEEDS_REVIEW_REQUIREMENT",
                        field=prefix,
                        severity=unresolved_severity,
                        category=IssueCategory.AMBIGUITY,
                        message=f"{requirement.raw_skill!r} needs mapping review.",
                        resolvable_by=[
                            "reconsider_mapping",
                            "request_clarification",
                            "escalate",
                        ],
                    )
                )
                if len(requirement.candidate_skill_ids) < 2:
                    issues.append(
                        _issue(
                            code="MISSING_REVIEW_CANDIDATES",
                            field=f"{prefix}.candidate_skill_ids",
                            severity=IssueSeverity.BLOCKING,
                            category=IssueCategory.MISSING_INFORMATION,
                            message="A needs-review mapping requires two candidates.",
                            resolvable_by=["reconsider_mapping", "rebuild_profile"],
                        )
                    )

            seen_candidate_ids: set[str] = set()
            for candidate_index, candidate_id in enumerate(
                requirement.candidate_skill_ids
            ):
                if self._taxonomy_repository.get_by_id(candidate_id) is None:
                    issues.append(
                        _issue(
                            code="UNKNOWN_CANDIDATE_SKILL_ID",
                            field=(f"{prefix}.candidate_skill_ids[{candidate_index}]"),
                            severity=IssueSeverity.BLOCKING,
                            category=IssueCategory.INVALID_VALUE,
                            message=(
                                f"Candidate skill ID {candidate_id!r} is not in "
                                "the taxonomy."
                            ),
                            resolvable_by=["lookup_taxonomy", "rebuild_profile"],
                        )
                    )
                if candidate_id in seen_candidate_ids:
                    issues.append(
                        _issue(
                            code="DUPLICATE_CANDIDATE_SKILL_ID",
                            field=(f"{prefix}.candidate_skill_ids[{candidate_index}]"),
                            severity=IssueSeverity.WARNING,
                            category=IssueCategory.DUPLICATE,
                            message=f"Candidate skill ID {candidate_id!r} is duplicated.",
                            resolvable_by=["rebuild_profile"],
                        )
                    )
                seen_candidate_ids.add(candidate_id)
        return issues


def _issue(
    *,
    code: str,
    field: str,
    severity: IssueSeverity,
    category: IssueCategory,
    message: str,
    resolvable_by: list[str],
) -> ValidationIssue:
    """Build one consistently structured validation issue."""
    return ValidationIssue(
        code=code,
        field=field,
        severity=severity,
        category=category,
        message=message,
        resolvable_by=resolvable_by,
    )
