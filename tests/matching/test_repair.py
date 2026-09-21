import random

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
    hard_requirements_covered,
    repair_assignment,
    repair_population,
    student_meets_requirement,
    students_for_project,
    preprocess_inputs,
)
from matching.preprocessing import MatchingContext


def student(
    student_id: str,
    skill_id: str = "python",
    level: int = 3,
) -> StudentProfile:
    return StudentProfile(
        student_id=student_id,
        name=student_id,
        skills=[StudentSkill(skill_id=skill_id, level=level)],
    )


def requirement(
    skill_id: str = "python",
    required_level: int = 1,
    requirement_type: RequirementType = RequirementType.PREFERRED,
) -> ProjectSkillRequirement:
    return ProjectSkillRequirement(
        skill_id=skill_id,
        required_level=required_level,
        requirement_type=requirement_type,
    )


def project(
    project_id: str,
    requirements: list[ProjectSkillRequirement] | None = None,
    min_team_size: int = 1,
    max_team_size: int = 3,
) -> ProjectProfile:
    return ProjectProfile(
        project_id=project_id,
        name=project_id,
        min_team_size=min_team_size,
        max_team_size=max_team_size,
        requirements=requirements or [],
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
            TaxonomyNode(
                skill_id="sql", name="SQL", parent_id="technology"
            ),
        ]
    )


def context(
    students: list[StudentProfile],
    projects: list[ProjectProfile],
) -> MatchingContext:
    return preprocess_inputs(
        MatchingInput(
            students=students,
            projects=projects,
            taxonomy=taxonomy(),
            constraints=MatchingConstraints(minimum_lca_depth=1),
        )
    )


def test_repair_returns_new_ordered_normalized_assignment() -> None:
    matching_context = context(
        [student("S2"), student("S1")],
        [project("P1", [requirement()], max_team_size=1)],
    )
    options = build_candidate_options(matching_context)
    original = {"unknown": "P1", "S1": "invalid", "S2": "P1"}

    repaired = repair_assignment(original, matching_context, options, random.Random(1))

    assert repaired is not original
    assert original == {"unknown": "P1", "S1": "invalid", "S2": "P1"}
    assert list(repaired) == ["S2", "S1"]
    assert set(repaired) == {"S2", "S1"}
    assert repaired == {"S2": "P1", "S1": None}


def test_project_within_capacity_remains_unchanged() -> None:
    matching_context = context(
        [student("S1"), student("S2")],
        [project("P1", [requirement()], max_team_size=2)],
    )
    options = build_candidate_options(matching_context)
    assignment = {"S1": "P1", "S2": "P1"}
    assert repair_assignment(
        assignment, matching_context, options, random.Random(1)
    ) == assignment


def test_over_capacity_project_is_reduced_reproducibly() -> None:
    matching_context = context(
        [student("S1"), student("S2"), student("S3")],
        [project("P1", [requirement()], max_team_size=1)],
    )
    options = build_candidate_options(matching_context)
    assignment = {"S1": "P1", "S2": "P1", "S3": "P1"}
    first = repair_assignment(assignment, matching_context, options, random.Random(8))
    second = repair_assignment(assignment, matching_context, options, random.Random(8))
    assert first == second
    assert len(students_for_project(first, "P1")) == 1


def test_student_meets_only_exact_skill_at_required_level() -> None:
    hard_python = requirement("python", 3, RequirementType.HARD_REQUIREMENT)
    assert student_meets_requirement(student("S1", "python", 3), hard_python)
    assert not student_meets_requirement(student("S1", "python", 2), hard_python)
    assert not student_meets_requirement(student("S1", "javascript", 5), hard_python)


def test_hard_requirements_are_team_level_and_all_must_be_covered() -> None:
    learners = [student("S1", "python", 3), student("S2", "sql", 2)]
    work = project(
        "P1",
        [
            requirement("python", 3, RequirementType.HARD_REQUIREMENT),
            requirement("sql", 2, RequirementType.HARD_REQUIREMENT),
        ],
    )
    matching_context = context(learners, [work])
    assert hard_requirements_covered(["S1", "S2"], work, matching_context)
    assert not hard_requirements_covered(["S1"], work, matching_context)


def test_missing_hard_requirement_recruits_suitable_unassigned_student() -> None:
    learners = [student("S1", "javascript", 5), student("S2", "python", 3)]
    work = project(
        "P1",
        [requirement("python", 3, RequirementType.HARD_REQUIREMENT)],
        max_team_size=2,
    )
    matching_context = context(learners, [work])
    options = build_candidate_options(matching_context)
    repaired = repair_assignment(
        {"S1": "P1", "S2": None},
        matching_context,
        options,
        random.Random(1),
    )
    assert repaired == {"S1": "P1", "S2": "P1"}


def test_uncovered_hard_requirement_deactivates_project() -> None:
    learner = student("S1", "javascript", 5)
    work = project(
        "P1", [requirement("python", 3, RequirementType.HARD_REQUIREMENT)]
    )
    matching_context = context([learner], [work])
    options = build_candidate_options(matching_context)
    assert repair_assignment(
        {"S1": "P1"}, matching_context, options, random.Random(1)
    ) == {"S1": None}


def test_below_required_level_does_not_cover_hard_requirement() -> None:
    learner = student("S1", "python", 2)
    work = project(
        "P1", [requirement("python", 3, RequirementType.HARD_REQUIREMENT)]
    )
    matching_context = context([learner], [work])
    options = build_candidate_options(matching_context)
    assert repair_assignment(
        {"S1": "P1"}, matching_context, options, random.Random(1)
    ) == {"S1": None}


def test_non_hard_requirements_do_not_deactivate_project() -> None:
    learner = student("S1", "python", 0)
    for requirement_type in (
        RequirementType.PREFERRED,
        RequirementType.LEARNING_OPPORTUNITY,
    ):
        work = project("P1", [requirement("python", 5, requirement_type)])
        matching_context = context([learner], [work])
        options = build_candidate_options(matching_context)
        assert repair_assignment(
            {"S1": "P1"}, matching_context, options, random.Random(1)
        ) == {"S1": "P1"}


def test_active_undersized_project_recruits_eligible_students() -> None:
    learners = [student("S1"), student("S2"), student("S3")]
    work = project(
        "P1", [requirement()], min_team_size=3, max_team_size=3
    )
    matching_context = context(learners, [work])
    options = build_candidate_options(matching_context)
    repaired = repair_assignment(
        {"S1": "P1", "S2": None, "S3": None},
        matching_context,
        options,
        random.Random(1),
    )
    assert repaired == {"S1": "P1", "S2": "P1", "S3": "P1"}


def test_project_that_cannot_reach_minimum_is_deactivated() -> None:
    work = project("P1", [requirement()], min_team_size=2, max_team_size=2)
    matching_context = context([student("S1")], [work])
    options = build_candidate_options(matching_context)
    assert repair_assignment(
        {"S1": "P1"}, matching_context, options, random.Random(1)
    ) == {"S1": None}


def test_empty_project_is_not_activated_for_minimum_size() -> None:
    work = project("P1", [requirement()], min_team_size=2, max_team_size=2)
    matching_context = context([student("S1"), student("S2")], [work])
    options = build_candidate_options(matching_context)
    assert repair_assignment(
        {"S1": None, "S2": None}, matching_context, options, random.Random(1)
    ) == {"S1": None, "S2": None}


def test_repair_never_exceeds_capacity_or_candidate_options() -> None:
    learners = [student("S1"), student("S2"), student("S3")]
    work = project("P1", [requirement()], max_team_size=2)
    matching_context = context(learners, [work])
    options = {
        "S1": (None, "P1"),
        "S2": (None, "P1"),
        "S3": (None,),
    }
    repaired = repair_assignment(
        {"S1": "P1", "S2": "P1", "S3": "P1"},
        matching_context,
        options,
        random.Random(1),
    )
    assert len(students_for_project(repaired, "P1")) <= 2
    assert all(value in options[key] for key, value in repaired.items())


def test_final_refill_uses_only_projects_that_remain_active() -> None:
    learners = [student("S1", "python"), student("S2", "python")]
    projects = [
        project(
            "P1", [requirement("sql", 5, RequirementType.HARD_REQUIREMENT)]
        ),
        project("P2", [requirement("python")], max_team_size=2),
    ]
    matching_context = context(learners, projects)
    options = {
        "S1": (None, "P1", "P2"),
        "S2": (None, "P2"),
    }
    repaired = repair_assignment(
        {"S1": "P1", "S2": "P2"},
        matching_context,
        options,
        random.Random(1),
    )
    assert repaired == {"S1": "P2", "S2": "P2"}


def test_repair_population_preserves_order_and_input() -> None:
    matching_context = context(
        [student("S1"), student("S2")],
        [project("P1", [requirement()], max_team_size=1)],
    )
    options = build_candidate_options(matching_context)
    population = [
        {"S1": "P1", "S2": "P1"},
        {"S1": None, "S2": "P1"},
    ]
    snapshot = [dict(assignment) for assignment in population]
    repaired = repair_population(
        population, matching_context, options, random.Random(3)
    )
    assert population == snapshot
    assert all(new is not old for new, old in zip(repaired, population, strict=True))
    assert repaired[1] == {"S1": None, "S2": "P1"}
