"""Genetic algorithm operators and execution loop."""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .assignment import (
    Assignment,
    Population,
    copy_assignment,
    create_initial_population,
)
from .preprocessing import MatchingContext
from .repair import repair_assignment, repair_population
from .scoring import ScoreBreakdown, calculate_fitness

ScoredAssignment = tuple[Assignment, float, ScoreBreakdown]

TARGET_SCORE_REACHED = "target_score_reached"
ALL_POSITIONS_FILLED = "all_positions_filled"
NO_IMPROVEMENT = "no_improvement"
MAX_GENERATIONS = "max_generations"


@dataclass(frozen=True)
class GAResult:
    assignment: Assignment
    final_score: float
    score_breakdown: ScoreBreakdown
    generations: int
    stop_reason: str


def evaluate_population(
    population: Sequence[Mapping[str, str | None]],
    context: MatchingContext,
) -> list[ScoredAssignment]:
    scored: list[ScoredAssignment] = []
    for original in population:
        assignment = copy_assignment(original)
        final_score, breakdown = calculate_fitness(assignment, context)
        scored.append((assignment, final_score, breakdown.copy()))
    return sorted(scored, key=lambda item: item[1], reverse=True)


def select_parent(
    scored_population: Sequence[ScoredAssignment],
    tournament_size: int,
    rng: random.Random,
) -> Assignment:
    if not scored_population:
        raise ValueError("scored_population must not be empty")
    if tournament_size <= 0:
        raise ValueError("tournament_size must be greater than 0")
    if tournament_size > len(scored_population):
        raise ValueError("tournament_size must not exceed population size")

    candidates = rng.sample(list(scored_population), tournament_size)
    winner = max(candidates, key=lambda item: item[1])
    return copy_assignment(winner[0])


def crossover(
    parent_a: Mapping[str, str | None],
    parent_b: Mapping[str, str | None],
    rng: random.Random,
) -> Assignment:
    if parent_a.keys() != parent_b.keys():
        raise ValueError("Parents must contain the same student IDs")
    return {
        student_id: (
            parent_a[student_id]
            if rng.random() < 0.5
            else parent_b[student_id]
        )
        for student_id in parent_a
    }


def mutate(
    assignment: Mapping[str, str | None],
    candidate_options: Mapping[str, Sequence[str | None]],
    mutation_rate: float,
    rng: random.Random,
) -> Assignment:
    if not 0 <= mutation_rate <= 1:
        raise ValueError("mutation_rate must be between 0 and 1")

    mutated: Assignment = {}
    for student_id, current_value in assignment.items():
        if student_id not in candidate_options:
            raise ValueError(f"Missing candidate options for student '{student_id}'")
        options = candidate_options[student_id]
        if not options:
            raise ValueError(f"Student '{student_id}' has no candidate options")
        if rng.random() < mutation_rate:
            mutated[student_id] = rng.choice(options)
        else:
            mutated[student_id] = current_value
    return mutated


def preserve_elites(
    scored_population: Sequence[ScoredAssignment],
    elite_count: int,
) -> Population:
    if elite_count < 0:
        raise ValueError("elite_count must be nonnegative")
    if elite_count > len(scored_population):
        raise ValueError("elite_count must not exceed population size")
    return [
        copy_assignment(assignment)
        for assignment, _, _ in scored_population[:elite_count]
    ]


def all_project_positions_filled(
    assignment: Mapping[str, str | None],
    context: MatchingContext,
) -> bool:
    if not context.projects:
        return False
    team_sizes = {project.project_id: 0 for project in context.projects}
    for student_id, project_id in assignment.items():
        if student_id not in context.students_by_id:
            continue
        if project_id in team_sizes:
            team_sizes[project_id] += 1
    return all(
        team_sizes[project.project_id] == project.max_team_size
        for project in context.projects
    )


def run_genetic_algorithm(
    context: MatchingContext,
    candidate_options: Mapping[str, Sequence[str | None]],
    rng: random.Random,
) -> GAResult:
    for student in context.students:
        if student.student_id not in candidate_options:
            raise ValueError(
                f"Missing candidate options for student '{student.student_id}'"
            )
        if not candidate_options[student.student_id]:
            raise ValueError(
                f"Student '{student.student_id}' has no candidate options"
            )

    config = context.config
    population = create_initial_population(
        candidate_options, config.population_size, rng
    )
    population = repair_population(population, context, candidate_options, rng)

    best_assignment: Assignment | None = None
    best_score = float("-inf")
    best_breakdown: ScoreBreakdown | None = None
    no_improvement_count = 0

    for generation in range(1, config.max_generations + 1):
        scored_population = evaluate_population(population, context)
        current_assignment, current_score, current_breakdown = scored_population[0]

        if current_score > best_score:
            best_assignment = copy_assignment(current_assignment)
            best_score = current_score
            best_breakdown = current_breakdown.copy()
            no_improvement_count = 0
        elif generation > 1:
            no_improvement_count += 1

        if best_assignment is None or best_breakdown is None:
            raise RuntimeError("Genetic algorithm failed to evaluate a population")

        if best_score >= config.target_score:
            stop_reason = TARGET_SCORE_REACHED
        elif all_project_positions_filled(best_assignment, context):
            stop_reason = ALL_POSITIONS_FILLED
        elif (
            generation > 1
            and config.patience > 0
            and no_improvement_count >= config.patience
        ):
            stop_reason = NO_IMPROVEMENT
        elif generation >= config.max_generations:
            stop_reason = MAX_GENERATIONS
        else:
            next_population = preserve_elites(
                scored_population, config.elite_count
            )
            while len(next_population) < config.population_size:
                parent_a = select_parent(
                    scored_population, config.tournament_size, rng
                )
                parent_b = select_parent(
                    scored_population, config.tournament_size, rng
                )
                child = crossover(parent_a, parent_b, rng)
                child = mutate(
                    child, candidate_options, config.mutation_rate, rng
                )
                child = repair_assignment(
                    child, context, candidate_options, rng
                )
                next_population.append(child)
            population = next_population
            continue

        return GAResult(
            assignment=copy_assignment(best_assignment),
            final_score=float(best_score),
            score_breakdown=best_breakdown.copy(),
            generations=generation,
            stop_reason=stop_reason,
        )

    raise RuntimeError("Genetic algorithm ended without a stopping condition")
