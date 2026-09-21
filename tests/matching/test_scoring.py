import pytest

from matching import (
    ASSIGNED_STUDENT_WEIGHT,
    GROWTH_WEIGHT,
    TEAM_COVERAGE_WEIGHT,
    UTILIZATION_WEIGHT,
    MatchingConstraints,
    MatchingInput,
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
    StudentSkill,
    TaxonomyNode,
    TaxonomyTree,
    assigned_student_score,
    calculate_fitness,
    growth_score,
    level_alignment,
    preprocess_inputs,
    skill_similarity,
    student_growth_opportunity_score,
    student_project_fit,
    student_requirement_fit,
    team_coverage_score,
    utilization_score,
)
from matching.preprocessing import MatchingContext


def skill(skill_id: str, level: int) -> StudentSkill:
    return StudentSkill(skill_id=skill_id, level=level)


def student(
    student_id: str,
    skills: list[StudentSkill] | None = None,
) -> StudentProfile:
    return StudentProfile(
        student_id=student_id,
        name=student_id,
        skills=skills or [],
    )


def requirement(
    skill_id: str,
    required_level: int,
    requirement_type: RequirementType = RequirementType.PREFERRED,
    importance: float = 1.0,
) -> ProjectSkillRequirement:
    return ProjectSkillRequirement(
        skill_id=skill_id,
        required_level=required_level,
        requirement_type=requirement_type,
        importance=importance,
    )


def project(
    project_id: str,
    requirements: list[ProjectSkillRequirement] | None = None,
) -> ProjectProfile:
    return ProjectProfile(
        project_id=project_id,
        name=project_id,
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
                skill_id="data", name="Data", parent_id="technology"
            ),
            TaxonomyNode(skill_id="sql", name="SQL", parent_id="data"),
            TaxonomyNode(skill_id="business", name="Business"),
            TaxonomyNode(
                skill_id="marketing", name="Marketing", parent_id="business"
            ),
        ]
    )


def context(
    students: list[StudentProfile] | None = None,
    projects: list[ProjectProfile] | None = None,
) -> MatchingContext:
    return preprocess_inputs(
        MatchingInput(
            students=students or [student("S1", [skill("python", 3)])],
            projects=projects
            or [project("P1", [requirement("python", 3)])],
            taxonomy=taxonomy(),
            constraints=MatchingConstraints(minimum_lca_depth=1),
        )
    )


def test_exact_skill_similarity() -> None:
    matching_context = context()
    assert skill_similarity("python", "python", matching_context) == 1.0


def test_related_skill_similarity() -> None:
    matching_context = context()
    assert skill_similarity("python", "javascript", matching_context) == 0.7


def test_unrelated_skill_similarity() -> None:
    matching_context = context()
    assert skill_similarity("python", "marketing", matching_context) == 0.0


def test_unknown_skill_similarity() -> None:
    matching_context = context()
    assert skill_similarity("unknown", "python", matching_context) == 0.0


def test_exact_unknown_skill_similarity() -> None:
    matching_context = context()
    assert skill_similarity("unknown", "unknown", matching_context) == 1.0


@pytest.mark.parametrize(
    ("student_level", "required_level", "expected"),
    [(0, 0, 1.0), (2, 4, 0.5), (4, 4, 1.0), (5, 4, 1.0), (0, 4, 0.0)],
)
def test_level_alignment(
    student_level: int,
    required_level: int,
    expected: float,
) -> None:
    assert level_alignment(student_level, required_level) == expected


def test_exact_student_requirement_fit() -> None:
    matching_context = context()
    learner = student("S1", [skill("python", 2)])
    needed = requirement("python", 4)
    assert student_requirement_fit(learner, needed, matching_context) == 50.0


def test_related_student_requirement_fit() -> None:
    matching_context = context()
    learner = student("S1", [skill("javascript", 4)])
    needed = requirement("python", 4)
    assert student_requirement_fit(learner, needed, matching_context) == 70.0


def test_unrelated_student_requirement_fit() -> None:
    matching_context = context()
    learner = student("S1", [skill("marketing", 5)])
    needed = requirement("python", 4)
    assert student_requirement_fit(learner, needed, matching_context) == 0.0


def test_student_requirement_fit_uses_best_skill() -> None:
    matching_context = context()
    learner = student(
        "S1",
        [skill("python", 2), skill("javascript", 4), skill("marketing", 5)],
    )
    needed = requirement("python", 4)
    assert student_requirement_fit(learner, needed, matching_context) == 70.0


def test_student_without_skills_has_zero_requirement_fit() -> None:
    matching_context = context()
    assert student_requirement_fit(
        student("S1"), requirement("python", 4), matching_context
    ) == 0.0


def test_project_fit_uses_importance_weighted_average() -> None:
    matching_context = context()
    learner = student("S1", [skill("python", 4)])
    work = project(
        "P1",
        [requirement("python", 4, importance=3), requirement("sql", 4)],
    )
    assert student_project_fit(learner, work, matching_context) == 75.0


def test_project_without_requirements_has_perfect_fit() -> None:
    matching_context = context()
    assert student_project_fit(student("S1"), project("P1"), matching_context) == 100.0


def test_assigned_student_score_averages_valid_assigned_pairs() -> None:
    learners = [
        student("S1", [skill("python", 4)]),
        student("S2", [skill("python", 2)]),
        student("S3", [skill("marketing", 5)]),
    ]
    work = project("P1", [requirement("python", 4)])
    matching_context = context(learners, [work])
    assignment = {"S1": "P1", "S2": "P1", "S3": None}
    assert assigned_student_score(assignment, matching_context) == 75.0


def test_unassigned_and_unknown_pairs_do_not_affect_assigned_score() -> None:
    learner = student("S1", [skill("python", 4)])
    work = project("P1", [requirement("python", 4)])
    matching_context = context([learner], [work])
    assignment = {
        "S1": "P1",
        "unknown": "P1",
        "also-unknown": "missing-project",
    }
    assert assigned_student_score(assignment, matching_context) == 100.0


def test_no_assigned_students_has_zero_assigned_score() -> None:
    assert assigned_student_score({"S1": None}, context()) == 0.0


@pytest.mark.parametrize(
    ("gap", "expected"),
    [(1, 100.0), (2, 75.0), (3, 50.0), (4, 25.0), (0, 0.0), (-1, 0.0), (5, 0.0)],
)
def test_exact_growth_gap_scores(gap: int, expected: float) -> None:
    matching_context = context()
    required_level = 5 if gap >= 0 else 2
    student_level = required_level - gap
    learner = student("S1", [skill("python", student_level)])
    needed = requirement(
        "python", required_level, RequirementType.LEARNING_OPPORTUNITY
    )
    assert student_growth_opportunity_score(
        learner, needed, matching_context
    ) == expected


def test_related_learning_skill_uses_similarity_multiplier() -> None:
    matching_context = context()
    learner = student("S1", [skill("javascript", 3)])
    needed = requirement("python", 4, RequirementType.LEARNING_OPPORTUNITY)
    assert student_growth_opportunity_score(
        learner, needed, matching_context
    ) == pytest.approx(70.0)


def test_growth_score_uses_importance_weighted_learning_requirements() -> None:
    learner = student("S1", [skill("python", 3)])
    work = project(
        "P1",
        [
            requirement(
                "python", 4, RequirementType.LEARNING_OPPORTUNITY, importance=3
            ),
            requirement(
                "sql", 4, RequirementType.LEARNING_OPPORTUNITY, importance=1
            ),
        ],
    )
    matching_context = context([learner], [work])
    assert growth_score({"S1": "P1"}, matching_context) == 75.0


@pytest.mark.parametrize(
    "requirement_type",
    [RequirementType.HARD_REQUIREMENT, RequirementType.PREFERRED],
)
def test_growth_ignores_non_learning_requirements(
    requirement_type: RequirementType,
) -> None:
    learner = student("S1", [skill("python", 0)])
    work = project("P1", [requirement("python", 5, requirement_type)])
    matching_context = context([learner], [work])
    assert growth_score({"S1": "P1"}, matching_context) == 100.0


def test_growth_is_neutral_without_learning_requirements() -> None:
    matching_context = context()
    assert growth_score({"S1": "P1"}, matching_context) == 100.0


def test_growth_is_zero_when_nobody_is_assigned() -> None:
    assert growth_score({"S1": None}, context()) == 0.0


def test_team_coverage_uses_best_member_for_each_requirement() -> None:
    learners = [
        student("S1", [skill("python", 4)]),
        student("S2", [skill("sql", 4)]),
    ]
    work = project(
        "P1", [requirement("python", 4), requirement("sql", 4)]
    )
    matching_context = context(learners, [work])
    assert team_coverage_score(
        {"S1": "P1", "S2": "P1"}, matching_context
    ) == 100.0


def test_empty_project_with_requirements_has_zero_coverage() -> None:
    assert team_coverage_score({"S1": None}, context()) == 0.0


def test_project_without_requirements_has_full_coverage() -> None:
    matching_context = context(projects=[project("P1")])
    assert team_coverage_score({"S1": None}, matching_context) == 100.0


def test_team_coverage_includes_inactive_projects() -> None:
    learner = student("S1", [skill("python", 4)])
    projects = [
        project("P1", [requirement("python", 4)]),
        project("P2", [requirement("python", 4)]),
    ]
    matching_context = context([learner], projects)
    assert team_coverage_score({"S1": "P1"}, matching_context) == 50.0


def test_utilization_uses_valid_assigned_students_over_total_students() -> None:
    learners = [student("S1"), student("S2"), student("S3")]
    matching_context = context(learners)
    assignment = {"S1": "P1", "S2": "P1", "S3": None}
    assert utilization_score(assignment, matching_context) == pytest.approx(
        200 / 3
    )


def test_unknown_keys_and_projects_do_not_count_toward_utilization() -> None:
    learners = [student("S1"), student("S2")]
    matching_context = context(learners)
    assignment = {"S1": "P1", "S2": "missing", "unknown": "P1"}
    assert utilization_score(assignment, matching_context) == 50.0


def test_calculate_fitness_uses_weights_and_exact_breakdown_keys() -> None:
    learner = student("S1", [skill("python", 3)])
    work = project(
        "P1",
        [requirement("python", 4, RequirementType.LEARNING_OPPORTUNITY)],
    )
    matching_context = context([learner], [work])
    final_score, breakdown = calculate_fitness({"S1": "P1"}, matching_context)
    assert set(breakdown) == {
        "assigned_student_score",
        "growth_score",
        "team_coverage_score",
        "utilization_score",
    }
    expected = (
        ASSIGNED_STUDENT_WEIGHT * breakdown["assigned_student_score"]
        + GROWTH_WEIGHT * breakdown["growth_score"]
        + TEAM_COVERAGE_WEIGHT * breakdown["team_coverage_score"]
        + UTILIZATION_WEIGHT * breakdown["utilization_score"]
    )
    assert final_score == pytest.approx(expected)
    assert sum(
        [
            ASSIGNED_STUDENT_WEIGHT,
            GROWTH_WEIGHT,
            TEAM_COVERAGE_WEIGHT,
            UTILIZATION_WEIGHT,
        ]
    ) == pytest.approx(1.0)


def test_all_scores_stay_normalized_and_scoring_is_pure_deterministic() -> None:
    assignment = {"S1": "P1"}
    snapshot = dict(assignment)
    matching_context = context()
    first = calculate_fitness(assignment, matching_context)
    second = calculate_fitness(assignment, matching_context)
    assert first == second
    assert assignment == snapshot
    final_score, breakdown = first
    assert 0.0 <= final_score <= 100.0
    assert all(0.0 <= score <= 100.0 for score in breakdown.values())
