import random

import pytest

from matching import (
    active_projects,
    copy_assignment,
    create_initial_population,
    create_random_assignment,
    group_assignment_by_project,
    students_for_project,
    unassigned_students,
)


def candidate_options() -> dict[str, tuple[str | None, ...]]:
    return {
        "S2": (None, "P2", "P1"),
        "S1": (None, "P1"),
        "S3": ("P2",),
    }


def test_copy_assignment_is_independent() -> None:
    original = {"S1": "P1", "S2": None}
    copied = copy_assignment(original)
    copied["S1"] = None
    assert copied is not original
    assert original == {"S1": "P1", "S2": None}


def test_students_for_project_preserves_student_order() -> None:
    assignment = {"S3": "P1", "S1": "P2", "S2": "P1", "S4": None}
    assert students_for_project(assignment, "P1") == ("S3", "S2")


def test_unassigned_students_preserves_order() -> None:
    assignment = {"S2": None, "S1": "P1", "S3": None}
    assert unassigned_students(assignment) == ("S2", "S3")


def test_active_projects_are_unique_and_preserve_first_appearance() -> None:
    assignment = {
        "S1": "P2",
        "S2": None,
        "S3": "P1",
        "S4": "P2",
        "S5": "P3",
    }
    assert active_projects(assignment) == ("P2", "P1", "P3")


def test_groups_assignment_by_active_project() -> None:
    assignment = {"S1": "P2", "S2": "P1", "S3": "P2", "S4": None}
    assert group_assignment_by_project(assignment) == {
        "P2": ("S1", "S3"),
        "P1": ("S2",),
    }


def test_random_assignment_has_each_student_in_input_order() -> None:
    options = candidate_options()
    assignment = create_random_assignment(options, random.Random(7))
    assert list(assignment) == list(options)
    assert set(assignment) == set(options)


def test_random_assignment_values_come_from_candidate_options() -> None:
    options = candidate_options()
    assignment = create_random_assignment(options, random.Random(7))
    assert all(value in options[key] for key, value in assignment.items())


def test_random_assignment_is_seeded() -> None:
    options = candidate_options()
    assert create_random_assignment(options, random.Random(42)) == (
        create_random_assignment(options, random.Random(42))
    )


def test_random_assignment_rejects_empty_candidate_options() -> None:
    with pytest.raises(ValueError, match="S1"):
        create_random_assignment({"S1": ()}, random.Random(1))


@pytest.mark.parametrize("population_size", [0, -1])
def test_initial_population_size_must_be_positive(population_size: int) -> None:
    with pytest.raises(ValueError, match="population_size"):
        create_initial_population(
            candidate_options(), population_size, random.Random(1)
        )


def test_initial_population_has_requested_size_and_order() -> None:
    options = candidate_options()
    population = create_initial_population(options, 5, random.Random(3))
    assert len(population) == 5
    assert all(list(assignment) == list(options) for assignment in population)


def test_population_assignments_are_independent() -> None:
    population = create_initial_population(
        {"S1": (None, "P1")}, 2, random.Random(3)
    )
    population[0]["S1"] = "changed"
    assert population[1]["S1"] != "changed"


def test_initial_population_is_seeded() -> None:
    options = candidate_options()
    assert create_initial_population(options, 5, random.Random(42)) == (
        create_initial_population(options, 5, random.Random(42))
    )
