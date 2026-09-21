"""Tests for deterministic project-profile validation."""

from dataclasses import FrozenInstanceError

import pytest

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    IssueSeverity,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    ProjectProfile,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
    TaxonomySkill,
    UnresolvedProjectRequirement,
)
from project_catalog_agent.profile import (
    ProfileValidationPolicy,
    ProjectProfileBuilder,
    ProjectProfileValidator,
)
from project_catalog_agent.taxonomy import JsonTaxonomyRepository


def build_profile(
    *,
    raw_skills: list[str] | None = None,
    importances: list[RequirementImportance] | None = None,
    levels: list[ProficiencyLevel | None] | None = None,
    confidences: list[float] | None = None,
    skill_id: str = "python",
    canonical_name: str = "Python",
) -> ProjectProfile:
    """Build a valid profile through the Step 6 builder."""
    skills = raw_skills or ["Python"]
    importance_values = importances or [RequirementImportance.HARD_REQUIREMENT]
    level_values = levels or [ProficiencyLevel.INTERMEDIATE]
    confidence_values = confidences or [0.9]
    evidence = [f"Evidence for {raw_skill}." for raw_skill in skills]
    description = " ".join(evidence)
    extraction = RequirementExtractionResult(
        project_summary="A validation test project.",
        requirements=[
            ExtractedRequirement(
                raw_skill=raw_skill,
                importance=importance_values[index],
                required_level=level_values[index],
                confidence=confidence_values[index],
                evidence_text=evidence[index],
                decision_basis=f"Decision for {raw_skill}.",
            )
            for index, raw_skill in enumerate(skills)
        ],
    )
    normalization = TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=index,
                raw_skill=raw_skill,
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id=skill_id,
                canonical_skill=canonical_name,
                decision_basis="Controlled taxonomy match.",
            )
            for index, raw_skill in enumerate(skills)
        ]
    )
    return ProjectProfileBuilder().build(
        request=CreateProjectRequest(
            request_id="validation-001",
            project_name="Validation Project",
            project_description=description,
        ),
        extraction=extraction,
        normalization=normalization,
    )


def validator(
    *,
    policy: ProfileValidationPolicy | None = None,
    repository: object | None = None,
) -> ProjectProfileValidator:
    """Build a validator using the packaged taxonomy by default."""
    return ProjectProfileValidator(
        taxonomy_repository=repository or JsonTaxonomyRepository(),  # type: ignore[arg-type]
        policy=policy,
    )


def codes(
    profile: ProjectProfile, *, policy: ProfileValidationPolicy | None = None
) -> list[str]:
    """Return issue codes for concise assertions."""
    return [issue.code for issue in validator(policy=policy).validate(profile).issues]


def with_requirement(profile: ProjectProfile, **updates: object) -> ProjectProfile:
    """Return a profile with updates applied to its first requirement."""
    updated = profile.requirements[0].model_copy(update=updates, deep=True)
    return profile.model_copy(update={"requirements": [updated]}, deep=True)


def unresolved_requirement(
    *,
    raw_skill: str = "Unknown Skill",
    source_index: int = 1,
    status: MappingStatus = MappingStatus.UNMAPPED,
    candidates: list[str] | None = None,
) -> UnresolvedProjectRequirement:
    """Build one structured unresolved requirement."""
    return UnresolvedProjectRequirement(
        source_requirement_index=source_index,
        raw_skill=raw_skill,
        mapping_status=status,
        importance=RequirementImportance.HARD_REQUIREMENT,
        required_level=ProficiencyLevel.INTERMEDIATE,
        evidence_text=f"Evidence for {raw_skill}.",
        candidate_skill_ids=candidates or [],
    )


def with_unresolved(
    profile: ProjectProfile,
    items: list[UnresolvedProjectRequirement],
) -> ProjectProfile:
    """Attach internally consistent structured unresolved information."""
    return profile.model_copy(
        update={
            "unresolved_requirements": items,
            "unresolved_skills": list(dict.fromkeys(item.raw_skill for item in items)),
        },
        deep=True,
    )


def test_valid_single_and_merged_profiles_have_no_issues() -> None:
    single = build_profile()
    merged = build_profile(
        raw_skills=["Python", "Python 3"],
        importances=[
            RequirementImportance.PREFERRED,
            RequirementImportance.HARD_REQUIREMENT,
        ],
        levels=[ProficiencyLevel.ENTRY, ProficiencyLevel.ADVANCED],
        confidences=[0.8, 0.95],
    )

    assert validator().validate(single).model_dump() == {"valid": True, "issues": []}
    assert validator().validate(merged).valid is True


def test_learning_opportunity_with_no_level_is_valid() -> None:
    profile = build_profile(
        importances=[RequirementImportance.LEARNING_OPPORTUNITY],
        levels=[None],
    )

    assert validator().validate(profile).valid is True


def test_warning_only_low_confidence_profile_remains_valid() -> None:
    profile = build_profile(confidences=[0.69])

    result = validator().validate(profile)

    assert result.valid is True
    assert [issue.code for issue in result.issues] == ["LOW_EXTRACTION_CONFIDENCE"]
    assert result.issues[0].severity is IssueSeverity.WARNING


def test_policy_is_frozen_and_validates_threshold() -> None:
    policy = ProfileValidationPolicy()

    with pytest.raises(FrozenInstanceError):
        policy.warn_on_low_confidence = False  # type: ignore[misc]
    with pytest.raises(ValueError, match="between 0 and 1"):
        ProfileValidationPolicy(low_confidence_threshold=1.1)


def test_no_resolved_requirements_is_blocking() -> None:
    profile = ProjectProfile(
        request_id="empty",
        project_name="Empty",
        project_description="No requirements.",
        project_summary="No resolved requirements.",
    )

    result = validator().validate(profile)

    assert result.valid is False
    assert codes(profile) == ["NO_RESOLVED_REQUIREMENTS"]


def test_duplicate_skill_ids_and_unresolved_list_mismatch_are_reported() -> None:
    profile = build_profile()
    duplicate = profile.requirements[0].model_copy(deep=True)
    profile = profile.model_copy(
        update={
            "requirements": [profile.requirements[0], duplicate],
            "unresolved_skills": ["Missing structured entry"],
        },
        deep=True,
    )

    result_codes = codes(profile)

    assert result_codes[:2] == [
        "DUPLICATE_CANONICAL_SKILL",
        "UNRESOLVED_LIST_MISMATCH",
    ]


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"skill_id": "not-in-taxonomy"}, "UNKNOWN_SKILL_ID"),
        ({"canonical_name": "Wrong Python"}, "CANONICAL_NAME_MISMATCH"),
        ({"required_level": None}, "MISSING_REQUIRED_LEVEL"),
        ({"provenance": []}, "EMPTY_PROVENANCE"),
        ({"evidence_text": "Invented evidence"}, "EVIDENCE_NOT_VERBATIM"),
        (
            {"importance": RequirementImportance.PREFERRED},
            "PROVENANCE_IMPORTANCE_CONFLICT",
        ),
        ({"required_level": ProficiencyLevel.ADVANCED}, "PROVENANCE_LEVEL_CONFLICT"),
    ],
)
def test_requirement_failures_are_returned(
    updates: dict[str, object],
    expected_code: str,
) -> None:
    result = validator().validate(with_requirement(build_profile(), **updates))

    assert result.valid is False
    assert expected_code in [issue.code for issue in result.issues]


def test_duplicate_provenance_source_index_is_reported() -> None:
    profile = build_profile()
    provenance = profile.requirements[0].provenance[0]
    profile = with_requirement(
        profile, provenance=[provenance, provenance.model_copy()]
    )

    assert "PROVENANCE_SKILL_INDEX_DUPLICATE" in codes(profile)


def test_provenance_evidence_must_be_verbatim() -> None:
    profile = build_profile()
    provenance = (
        profile.requirements[0]
        .provenance[0]
        .model_copy(update={"evidence_text": "Invented provenance evidence"})
    )
    profile = with_requirement(profile, provenance=[provenance])

    assert "PROVENANCE_EVIDENCE_NOT_VERBATIM" in codes(profile)


class InactivePythonRepository:
    """Return an inactive Python record while delegating other lookups."""

    def __init__(self) -> None:
        self._delegate = JsonTaxonomyRepository()

    def get_by_id(self, skill_id: str) -> TaxonomySkill | None:
        """Return Python as inactive."""
        skill = self._delegate.get_by_id(skill_id)
        if skill is not None and skill_id == "python":
            return skill.model_copy(update={"active": False})
        return skill


def test_inactive_taxonomy_skill_is_blocking() -> None:
    result = validator(repository=InactivePythonRepository()).validate(build_profile())

    assert result.valid is False
    assert [issue.code for issue in result.issues] == ["INACTIVE_SKILL"]


@pytest.mark.parametrize(
    ("status", "candidates", "expected_codes"),
    [
        (MappingStatus.UNMAPPED, [], ["UNMAPPED_REQUIREMENT"]),
        (
            MappingStatus.NEEDS_REVIEW,
            ["aws", "gcp-azure"],
            ["NEEDS_REVIEW_REQUIREMENT"],
        ),
        (
            MappingStatus.NEEDS_REVIEW,
            ["aws"],
            ["NEEDS_REVIEW_REQUIREMENT", "MISSING_REVIEW_CANDIDATES"],
        ),
        (
            MappingStatus.NEEDS_REVIEW,
            ["aws", "invented"],
            ["NEEDS_REVIEW_REQUIREMENT", "UNKNOWN_CANDIDATE_SKILL_ID"],
        ),
        (
            MappingStatus.NEEDS_REVIEW,
            ["aws", "aws"],
            ["NEEDS_REVIEW_REQUIREMENT", "DUPLICATE_CANDIDATE_SKILL_ID"],
        ),
    ],
)
def test_unresolved_requirement_rules(
    status: MappingStatus,
    candidates: list[str],
    expected_codes: list[str],
) -> None:
    profile = with_unresolved(
        build_profile(),
        [unresolved_requirement(status=status, candidates=candidates)],
    )

    unresolved_codes = [
        issue.code
        for issue in validator().validate(profile).issues
        if issue.field.startswith("unresolved_requirements")
    ]

    assert unresolved_codes == expected_codes


def test_unmapped_candidates_are_allowed_when_known() -> None:
    profile = with_unresolved(
        build_profile(),
        [
            unresolved_requirement(
                status=MappingStatus.UNMAPPED,
                candidates=["aws"],
            )
        ],
    )

    assert codes(profile) == ["UNMAPPED_REQUIREMENT"]


def test_source_collision_and_duplicate_unresolved_index_are_reported() -> None:
    profile = build_profile()
    profile = with_unresolved(
        profile,
        [
            unresolved_requirement(raw_skill="First", source_index=0),
            unresolved_requirement(raw_skill="Second", source_index=0),
        ],
    )

    result_codes = codes(profile)

    assert result_codes.count("SOURCE_INDEX_COLLISION") == 2
    assert "DUPLICATE_UNRESOLVED_SOURCE_INDEX" in result_codes


def test_nonblocking_unresolved_policy_keeps_profile_valid() -> None:
    profile = with_unresolved(build_profile(), [unresolved_requirement()])
    policy = ProfileValidationPolicy(block_all_unresolved_requirements=False)

    result = validator(policy=policy).validate(profile)

    assert result.valid is True
    assert result.issues[0].severity is IssueSeverity.WARNING


def test_issue_order_is_deterministic_and_all_issues_are_structured() -> None:
    profile = build_profile()
    bad_requirement = profile.requirements[0].model_copy(
        update={
            "skill_id": "unknown",
            "evidence_text": "Not verbatim",
        },
        deep=True,
    )
    bad_provenance = bad_requirement.provenance[0].model_copy(
        update={"evidence_text": "Also not verbatim"}
    )
    bad_requirement = bad_requirement.model_copy(
        update={"provenance": [bad_provenance]}
    )
    unresolved = unresolved_requirement(source_index=2)
    profile = profile.model_copy(
        update={
            "requirements": [bad_requirement],
            "unresolved_skills": ["wrong"],
            "unresolved_requirements": [unresolved],
        },
        deep=True,
    )

    result = validator().validate(profile)

    assert [issue.code for issue in result.issues] == [
        "UNRESOLVED_LIST_MISMATCH",
        "UNKNOWN_SKILL_ID",
        "EVIDENCE_NOT_VERBATIM",
        "PROVENANCE_EVIDENCE_NOT_VERBATIM",
        "UNMAPPED_REQUIREMENT",
    ]
    assert result.valid is False
    assert all(issue.code and issue.field and issue.message for issue in result.issues)
    assert all(issue.resolvable_by for issue in result.issues)


def test_validation_does_not_mutate_profile_or_taxonomy() -> None:
    repository = JsonTaxonomyRepository()
    profile = build_profile()
    profile_before = profile.model_dump()
    taxonomy_before = [skill.model_dump() for skill in repository.list_skills()]

    ProjectProfileValidator(taxonomy_repository=repository).validate(profile)

    assert profile.model_dump() == profile_before
    assert [skill.model_dump() for skill in repository.list_skills()] == taxonomy_before


class CrashingRepository:
    """Simulate an unexpected taxonomy infrastructure failure."""

    def get_by_id(self, skill_id: str) -> TaxonomySkill | None:
        """Raise instead of returning an ordinary lookup result."""
        raise RuntimeError("taxonomy unavailable")


def test_unexpected_repository_failure_propagates() -> None:
    with pytest.raises(RuntimeError, match="taxonomy unavailable"):
        validator(repository=CrashingRepository()).validate(build_profile())
