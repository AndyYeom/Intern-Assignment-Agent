"""Normalized component scores and final matching fitness."""

from collections.abc import Mapping
from typing import TypedDict

from .preprocessing import MatchingContext
from .schemas import (
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
)
from .taxonomy import are_taxonomically_related

ASSIGNED_STUDENT_WEIGHT = 0.40
GROWTH_WEIGHT = 0.25
TEAM_COVERAGE_WEIGHT = 0.25
UTILIZATION_WEIGHT = 0.10

EXACT_SKILL_SIMILARITY = 1.0
RELATED_SKILL_SIMILARITY = 0.7
NO_SKILL_SIMILARITY = 0.0


class ScoreBreakdown(TypedDict):
    assigned_student_score: float
    growth_score: float
    team_coverage_score: float
    utilization_score: float


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def skill_similarity(
    student_skill_id: str,
    requirement_skill_id: str,
    context: MatchingContext,
) -> float:
    if student_skill_id == requirement_skill_id:
        return EXACT_SKILL_SIMILARITY
    try:
        related = are_taxonomically_related(
            student_skill_id,
            requirement_skill_id,
            context.taxonomy_parent_by_id,
            context.constraints.minimum_lca_depth,
        )
    except KeyError:
        return NO_SKILL_SIMILARITY
    if related:
        return RELATED_SKILL_SIMILARITY
    return NO_SKILL_SIMILARITY


def level_alignment(student_level: int, required_level: int) -> float:
    if required_level == 0:
        return 1.0
    return min(student_level / required_level, 1.0)


def student_requirement_fit(
    student: StudentProfile,
    requirement: ProjectSkillRequirement,
    context: MatchingContext,
) -> float:
    return _clamp_score(
        max(
            (
                100.0
                * skill_similarity(skill.skill_id, requirement.skill_id, context)
                * level_alignment(skill.level, requirement.required_level)
                for skill in student.skills
            ),
            default=0.0,
        )
    )


def student_project_fit(
    student: StudentProfile,
    project: ProjectProfile,
    context: MatchingContext,
) -> float:
    if not project.requirements:
        return 100.0
    total_importance = sum(
        requirement.importance for requirement in project.requirements
    )
    weighted_fit = sum(
        student_requirement_fit(student, requirement, context)
        * requirement.importance
        for requirement in project.requirements
    )
    return _clamp_score(weighted_fit / total_importance)


def assigned_student_score(
    assignment: Mapping[str, str | None],
    context: MatchingContext,
) -> float:
    fits: list[float] = []
    for student_id, project_id in assignment.items():
        if project_id is None:
            continue
        student = context.students_by_id.get(student_id)
        project = context.projects_by_id.get(project_id)
        if student is None or project is None:
            continue
        fits.append(student_project_fit(student, project, context))
    if not fits:
        return 0.0
    return _clamp_score(sum(fits) / len(fits))


def student_growth_opportunity_score(
    student: StudentProfile,
    requirement: ProjectSkillRequirement,
    context: MatchingContext,
) -> float:
    gap_scores = {1: 100.0, 2: 75.0, 3: 50.0, 4: 25.0}
    return _clamp_score(
        max(
            (
                gap_scores.get(requirement.required_level - skill.level, 0.0)
                * skill_similarity(skill.skill_id, requirement.skill_id, context)
                for skill in student.skills
            ),
            default=0.0,
        )
    )


def growth_score(
    assignment: Mapping[str, str | None],
    context: MatchingContext,
) -> float:
    valid_pair_count = 0
    weighted_score = 0.0
    total_importance = 0.0

    for student_id, project_id in assignment.items():
        if project_id is None:
            continue
        student = context.students_by_id.get(student_id)
        project = context.projects_by_id.get(project_id)
        if student is None or project is None:
            continue
        valid_pair_count += 1
        for requirement in project.requirements:
            if requirement.requirement_type is not RequirementType.LEARNING_OPPORTUNITY:
                continue
            weighted_score += (
                student_growth_opportunity_score(student, requirement, context)
                * requirement.importance
            )
            total_importance += requirement.importance

    if valid_pair_count == 0:
        return 0.0
    if total_importance == 0:
        return 100.0
    return _clamp_score(weighted_score / total_importance)


def team_coverage_score(
    assignment: Mapping[str, str | None],
    context: MatchingContext,
) -> float:
    if not context.projects:
        return 0.0

    project_scores: list[float] = []
    for project in context.projects:
        if not project.requirements:
            project_scores.append(100.0)
            continue

        assigned_students = [
            student
            for student in context.students
            if assignment.get(student.student_id) == project.project_id
        ]
        total_importance = sum(
            requirement.importance for requirement in project.requirements
        )
        weighted_coverage = sum(
            max(
                (
                    student_requirement_fit(student, requirement, context)
                    for student in assigned_students
                ),
                default=0.0,
            )
            * requirement.importance
            for requirement in project.requirements
        )
        project_scores.append(weighted_coverage / total_importance)

    return _clamp_score(sum(project_scores) / len(project_scores))


def utilization_score(
    assignment: Mapping[str, str | None],
    context: MatchingContext,
) -> float:
    if not context.students:
        return 0.0
    valid_assigned_count = sum(
        1
        for student in context.students
        if assignment.get(student.student_id) in context.projects_by_id
    )
    return _clamp_score(100.0 * valid_assigned_count / len(context.students))


def calculate_fitness(
    assignment: Mapping[str, str | None],
    context: MatchingContext,
) -> tuple[float, ScoreBreakdown]:
    breakdown: ScoreBreakdown = {
        "assigned_student_score": assigned_student_score(assignment, context),
        "growth_score": growth_score(assignment, context),
        "team_coverage_score": team_coverage_score(assignment, context),
        "utilization_score": utilization_score(assignment, context),
    }
    final_score = (
        ASSIGNED_STUDENT_WEIGHT * breakdown["assigned_student_score"]
        + GROWTH_WEIGHT * breakdown["growth_score"]
        + TEAM_COVERAGE_WEIGHT * breakdown["team_coverage_score"]
        + UTILIZATION_WEIGHT * breakdown["utilization_score"]
    )
    return _clamp_score(float(final_score)), breakdown
