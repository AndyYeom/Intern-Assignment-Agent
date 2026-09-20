from dataclasses import replace

import pytest

from matching import (
    MatchingConstraints,
    MatchingInput,
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
    StudentSkill,
    TaxonomyNode,
    TaxonomyTree,
    build_candidate_options,
    has_exact_skill_match,
    has_taxonomy_skill_match,
    is_candidate_project,
    preprocess_inputs,
)
from matching.preprocessing import MatchingContext


def skill(skill_id: str, level: int = 1) -> StudentSkill:
    return StudentSkill(skill_id=skill_id, level=level)


def student(
    student_id: str,
    skill_id: str | None = None,
    level: int = 1,
) -> StudentProfile:
    skills = [] if skill_id is None else [skill(skill_id, level)]
    return StudentProfile(student_id=student_id, name=student_id, skills=skills)


def project(
    project_id: str,
    skill_id: str | None = None,
    required_level: int = 1,
    requirement_type: RequirementType = RequirementType.PREFERRED,
) -> ProjectProfile:
    requirements = []
    if skill_id is not None:
        requirements.append(
            ProjectSkillRequirement(
                skill_id=skill_id,
                required_level=required_level,
                requirement_type=requirement_type,
            )
        )
    return ProjectProfile(
        project_id=project_id,
        name=project_id,
        requirements=requirements,
    )


def taxonomy() -> TaxonomyTree:
    return TaxonomyTree(
        nodes=[
            TaxonomyNode(skill_id="technology", name="Technology"),
            TaxonomyNode(
                skill_id="programming",
                name="Programming",
                parent_id="technology",
            ),
            TaxonomyNode(
                skill_id="python", name="Python", parent_id="programming"
            ),
            TaxonomyNode(
                skill_id="javascript",
                name="JavaScript",
                parent_id="programming",
            ),
            TaxonomyNode(skill_id="business", name="Business"),
            TaxonomyNode(
                skill_id="marketing", name="Marketing", parent_id="business"
            ),
        ]
    )


def context(
    students: list[StudentProfile] | None = None,
    projects: list[ProjectProfile] | None = None,
    minimum_lca_depth: int = 1,
    allow_unassigned: bool = True,
) -> MatchingContext:
    data = MatchingInput(
        students=students or [student("S1", "python")],
        projects=projects or [project("P1", "python")],
        taxonomy=taxonomy(),
        constraints=MatchingConstraints(
            minimum_lca_depth=minimum_lca_depth,
            allow_unassigned=allow_unassigned,
        ),
    )
    return preprocess_inputs(data)


def test_exact_skill_match() -> None:
    assert has_exact_skill_match(student("S1", "python"), project("P1", "python"))


def test_no_exact_skill_match() -> None:
    assert not has_exact_skill_match(
        student("S1", "python"), project("P1", "javascript")
    )


def test_sibling_taxonomy_skills_match_at_threshold() -> None:
    matching_context = context()
    assert has_taxonomy_skill_match(
        student("S1", "python"),
        project("P1", "javascript"),
        matching_context.taxonomy_parent_by_id,
        1,
    )


def test_skills_from_separate_roots_do_not_match() -> None:
    matching_context = context()
    assert not has_taxonomy_skill_match(
        student("S1", "python"),
        project("P1", "marketing"),
        matching_context.taxonomy_parent_by_id,
        0,
    )


def test_related_skills_fail_high_threshold() -> None:
    matching_context = context()
    assert not has_taxonomy_skill_match(
        student("S1", "python"),
        project("P1", "javascript"),
        matching_context.taxonomy_parent_by_id,
        2,
    )


def test_unknown_taxonomy_skills_are_skipped() -> None:
    matching_context = context()
    assert not has_taxonomy_skill_match(
        student("S1", "unknown-student"),
        project("P1", "unknown-project"),
        matching_context.taxonomy_parent_by_id,
        0,
    )


def test_exact_unknown_skill_is_still_a_candidate() -> None:
    learner = student("S1", "unknown")
    work = project("P1", "unknown")
    matching_context = context(students=[learner], projects=[work])
    assert is_candidate_project(learner, work, matching_context)


def test_project_without_requirements_is_not_a_candidate() -> None:
    learner = student("S1", "python")
    work = project("P1")
    matching_context = context(students=[learner], projects=[work])
    assert not is_candidate_project(learner, work, matching_context)


def test_skill_levels_are_ignored() -> None:
    learner = student("S1", "python", level=0)
    work = project("P1", "python", required_level=5)
    matching_context = context(students=[learner], projects=[work])
    assert is_candidate_project(learner, work, matching_context)


@pytest.mark.parametrize("requirement_type", list(RequirementType))
def test_requirement_type_is_ignored(
    requirement_type: RequirementType,
) -> None:
    learner = student("S1", "python")
    work = project("P1", "python", requirement_type=requirement_type)
    matching_context = context(students=[learner], projects=[work])
    assert is_candidate_project(learner, work, matching_context)


def test_candidate_options_preserve_project_order() -> None:
    matching_context = context(
        projects=[project("P2", "python"), project("P1", "javascript")]
    )
    assert build_candidate_options(matching_context)["S1"] == (None, "P2", "P1")


def test_candidate_options_preserve_student_order() -> None:
    matching_context = context(
        students=[student("S2", "python"), student("S1", "python")]
    )
    assert list(build_candidate_options(matching_context)) == ["S2", "S1"]


def test_none_is_first_when_unassigned_is_allowed() -> None:
    assert build_candidate_options(context())["S1"] == (None, "P1")


def test_none_is_omitted_when_unassigned_is_disallowed() -> None:
    assert build_candidate_options(context(allow_unassigned=False))["S1"] == ("P1",)


@pytest.mark.parametrize(
    ("allow_unassigned", "expected"),
    [(True, (None,)), (False, ())],
)
def test_student_without_candidates_gets_expected_options(
    allow_unassigned: bool,
    expected: tuple[str | None, ...],
) -> None:
    matching_context = context(
        students=[student("S1", "python")],
        projects=[project("P1", "marketing")],
        allow_unassigned=allow_unassigned,
    )
    assert build_candidate_options(matching_context)["S1"] == expected


def test_candidate_options_do_not_repeat_project_ids() -> None:
    matching_context = context()
    duplicate_context = replace(
        matching_context,
        projects=(matching_context.projects[0], matching_context.projects[0]),
    )
    assert build_candidate_options(duplicate_context)["S1"] == (None, "P1")


def test_candidate_options_are_deterministic() -> None:
    matching_context = context(
        students=[student("S2", "javascript"), student("S1", "python")],
        projects=[project("P2", "python"), project("P1", "javascript")],
    )
    assert build_candidate_options(matching_context) == build_candidate_options(
        matching_context
    )
