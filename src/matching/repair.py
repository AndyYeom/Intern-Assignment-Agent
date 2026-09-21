"""Simple deterministic-order assignment repair."""

import random
from collections.abc import Mapping, Sequence

from .assignment import Assignment, Population, students_for_project
from .preprocessing import MatchingContext
from .schemas import (
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
)


def student_meets_requirement(
    student: StudentProfile,
    requirement: ProjectSkillRequirement,
) -> bool:
    return any(
        skill.skill_id == requirement.skill_id
        and skill.level >= requirement.required_level
        for skill in student.skills
    )


def hard_requirements_covered(
    student_ids: Sequence[str],
    project: ProjectProfile,
    context: MatchingContext,
) -> bool:
    hard_requirements = (
        requirement
        for requirement in project.requirements
        if requirement.requirement_type is RequirementType.HARD_REQUIREMENT
    )
    return all(
        any(
            student_id in context.students_by_id
            and student_meets_requirement(
                context.students_by_id[student_id], requirement
            )
            for student_id in student_ids
        )
        for requirement in hard_requirements
    )


def repair_assignment(
    assignment: Mapping[str, str | None],
    context: MatchingContext,
    candidate_options: Mapping[str, Sequence[str | None]],
    rng: random.Random,
) -> Assignment:
    repaired: Assignment = {}

    # Phase 1: normalize genes to known students and valid candidate projects.
    for student in context.students:
        assigned_project_id = assignment.get(student.student_id)
        options = candidate_options.get(student.student_id, ())
        if assigned_project_id is None or assigned_project_id in options:
            repaired[student.student_id] = assigned_project_id
        else:
            repaired[student.student_id] = None

    # Phase 2: enforce maximum team sizes.
    for project in context.projects:
        assigned_students = students_for_project(repaired, project.project_id)
        if len(assigned_students) <= project.max_team_size:
            continue
        kept_students = set(rng.sample(assigned_students, project.max_team_size))
        for student_id in assigned_students:
            if student_id not in kept_students:
                repaired[student_id] = None

    # Phase 3: recruit unassigned students for uncovered hard requirements.
    for project in context.projects:
        team = list(students_for_project(repaired, project.project_id))
        if not team:
            continue
        hard_requirements = (
            requirement
            for requirement in project.requirements
            if requirement.requirement_type is RequirementType.HARD_REQUIREMENT
        )
        for requirement in hard_requirements:
            if any(
                student_meets_requirement(
                    context.students_by_id[student_id], requirement
                )
                for student_id in team
            ):
                continue
            if len(team) >= project.max_team_size:
                break
            for student in context.students:
                if repaired[student.student_id] is not None:
                    continue
                if project.project_id not in candidate_options.get(
                    student.student_id, ()
                ):
                    continue
                if not student_meets_requirement(student, requirement):
                    continue
                repaired[student.student_id] = project.project_id
                team.append(student.student_id)
                break

    # Phase 4: fill active projects to their minimum team sizes.
    for project in context.projects:
        team = list(students_for_project(repaired, project.project_id))
        if not team:
            continue
        for student in context.students:
            if len(team) >= project.min_team_size:
                break
            if len(team) >= project.max_team_size:
                break
            if repaired[student.student_id] is not None:
                continue
            if project.project_id not in candidate_options.get(student.student_id, ()):
                continue
            repaired[student.student_id] = project.project_id
            team.append(student.student_id)

    # Phase 5: deactivate active projects that remain infeasible.
    for project in context.projects:
        team = students_for_project(repaired, project.project_id)
        if not team:
            continue
        if len(team) < project.min_team_size or not hard_requirements_covered(
            team, project, context
        ):
            for student_id in team:
                repaired[student_id] = None

    # Phase 6: refill only projects that remain active.
    active_project_ids = {
        project.project_id
        for project in context.projects
        if students_for_project(repaired, project.project_id)
    }
    team_sizes = {
        project_id: len(students_for_project(repaired, project_id))
        for project_id in active_project_ids
    }
    for student in context.students:
        if repaired[student.student_id] is not None:
            continue
        for project_id in candidate_options.get(student.student_id, ()):
            if project_id is None or project_id not in active_project_ids:
                continue
            project = context.projects_by_id.get(project_id)
            if project is None or team_sizes[project_id] >= project.max_team_size:
                continue
            repaired[student.student_id] = project_id
            team_sizes[project_id] += 1
            break

    return repaired


def repair_population(
    population: Sequence[Mapping[str, str | None]],
    context: MatchingContext,
    candidate_options: Mapping[str, Sequence[str | None]],
    rng: random.Random,
) -> Population:
    return [
        repair_assignment(assignment, context, candidate_options, rng)
        for assignment in population
    ]
