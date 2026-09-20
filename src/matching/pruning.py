"""Deterministic student-project candidate pruning."""

from collections.abc import Mapping

from .preprocessing import MatchingContext
from .schemas import ProjectProfile, StudentProfile
from .taxonomy import are_taxonomically_related

CandidateOptions = dict[str, tuple[str | None, ...]]


def has_exact_skill_match(
    student: StudentProfile,
    project: ProjectProfile,
) -> bool:
    student_skill_ids = {skill.skill_id for skill in student.skills}
    return any(
        requirement.skill_id in student_skill_ids
        for requirement in project.requirements
    )


def has_taxonomy_skill_match(
    student: StudentProfile,
    project: ProjectProfile,
    parent_by_id: Mapping[str, str | None],
    minimum_lca_depth: int,
) -> bool:
    if minimum_lca_depth < 0:
        raise ValueError("minimum_lca_depth must be nonnegative")

    for skill in student.skills:
        for requirement in project.requirements:
            if skill.skill_id == requirement.skill_id:
                return True
            try:
                if are_taxonomically_related(
                    skill.skill_id,
                    requirement.skill_id,
                    parent_by_id,
                    minimum_lca_depth,
                ):
                    return True
            except KeyError:
                continue
    return False


def is_candidate_project(
    student: StudentProfile,
    project: ProjectProfile,
    context: MatchingContext,
) -> bool:
    if not project.requirements:
        return False
    return has_exact_skill_match(
        student, project
    ) or has_taxonomy_skill_match(
        student,
        project,
        context.taxonomy_parent_by_id,
        context.constraints.minimum_lca_depth,
    )


def build_candidate_options(context: MatchingContext) -> CandidateOptions:
    options_by_student: CandidateOptions = {}

    for student in context.students:
        options: list[str | None] = []
        if context.constraints.allow_unassigned:
            options.append(None)

        seen_project_ids: set[str] = set()
        for project in context.projects:
            if project.project_id in seen_project_ids:
                continue
            seen_project_ids.add(project.project_id)
            if is_candidate_project(student, project, context):
                options.append(project.project_id)

        options_by_student[student.student_id] = tuple(options)

    return options_by_student
