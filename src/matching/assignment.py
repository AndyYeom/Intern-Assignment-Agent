"""Assignment representation and random population initialization."""

import random
from collections.abc import Mapping, Sequence

Assignment = dict[str, str | None]
Population = list[Assignment]


def copy_assignment(
    assignment: Mapping[str, str | None],
) -> Assignment:
    return dict(assignment)


def students_for_project(
    assignment: Mapping[str, str | None],
    project_id: str,
) -> tuple[str, ...]:
    return tuple(
        student_id
        for student_id, assigned_project_id in assignment.items()
        if assigned_project_id == project_id
    )


def unassigned_students(
    assignment: Mapping[str, str | None],
) -> tuple[str, ...]:
    return tuple(
        student_id
        for student_id, project_id in assignment.items()
        if project_id is None
    )


def active_projects(
    assignment: Mapping[str, str | None],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            project_id
            for project_id in assignment.values()
            if project_id is not None
        )
    )


def group_assignment_by_project(
    assignment: Mapping[str, str | None],
) -> dict[str, tuple[str, ...]]:
    return {
        project_id: students_for_project(assignment, project_id)
        for project_id in active_projects(assignment)
    }


def create_random_assignment(
    candidate_options: Mapping[str, Sequence[str | None]],
    rng: random.Random,
) -> Assignment:
    assignment: Assignment = {}
    for student_id, options in candidate_options.items():
        if not options:
            raise ValueError(f"Student '{student_id}' has no candidate options")
        assignment[student_id] = rng.choice(options)
    return assignment


def create_initial_population(
    candidate_options: Mapping[str, Sequence[str | None]],
    population_size: int,
    rng: random.Random,
) -> Population:
    if population_size <= 0:
        raise ValueError("population_size must be greater than 0")
    return [
        create_random_assignment(candidate_options, rng)
        for _ in range(population_size)
    ]
