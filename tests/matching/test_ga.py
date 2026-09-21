import random

import pytest

import matching.ga as ga_module
from matching import (
    ALL_POSITIONS_FILLED,
    MAX_GENERATIONS,
    NO_IMPROVEMENT,
    TARGET_SCORE_REACHED,
    GAConfig,
    GAResult,
    MatchingConstraints,
    MatchingInput,
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
    StudentSkill,
    TaxonomyNode,
    TaxonomyTree,
    all_project_positions_filled,
    build_candidate_options,
    calculate_fitness,
    crossover,
    evaluate_population,
    mutate,
    preserve_elites,
    preprocess_inputs,
    run_genetic_algorithm,
    select_parent,
)
from matching.preprocessing import MatchingContext
from matching.scoring import ScoreBreakdown


def student(
    student_id: str,
    level: int = 4,
) -> StudentProfile:
    return StudentProfile(
        student_id=student_id,
        name=student_id,
        skills=[StudentSkill(skill_id="python", level=level)],
    )


def project(
    project_id: str = "P1",
    max_team_size: int = 2,
    learning: bool = False,
) -> ProjectProfile:
    requirement_type = (
        RequirementType.LEARNING_OPPORTUNITY
        if learning
        else RequirementType.PREFERRED
    )
    return ProjectProfile(
        project_id=project_id,
        name=project_id,
        max_team_size=max_team_size,
        requirements=[
            ProjectSkillRequirement(
                skill_id="python",
                required_level=1 if learning else 4,
                requirement_type=requirement_type,
            )
        ],
    )


def context(
    students: list[StudentProfile] | None = None,
    projects: list[ProjectProfile] | None = None,
    *,
    population_size: int = 4,
    max_generations: int = 3,
    mutation_rate: float = 0.1,
    elite_count: int = 1,
    tournament_size: int = 2,
    target_score: float = 100.0,
    patience: int = 0,
    allow_unassigned: bool = True,
) -> MatchingContext:
    data = MatchingInput(
        students=students or [student("S1")],
        projects=projects or [project()],
        taxonomy=TaxonomyTree(
            nodes=[TaxonomyNode(skill_id="python", name="Python")]
        ),
        constraints=MatchingConstraints(allow_unassigned=allow_unassigned),
        config=GAConfig(
            population_size=population_size,
            max_generations=max_generations,
            mutation_rate=mutation_rate,
            elite_count=elite_count,
            tournament_size=tournament_size,
            target_score=target_score,
            patience=patience,
            seed=42,
        ),
    )
    return preprocess_inputs(data)


def breakdown(score: float) -> ScoreBreakdown:
    return {
        "assigned_student_score": score,
        "growth_score": score,
        "team_coverage_score": score,
        "utilization_score": score,
    }


def scored(
    assignment: dict[str, str | None], score: float
) -> tuple[dict[str, str | None], float, ScoreBreakdown]:
    return assignment, score, breakdown(score)


def test_evaluate_population_sorts_high_to_low_without_mutation() -> None:
    matching_context = context()
    population = [{"S1": None}, {"S1": "P1"}]
    snapshot = [dict(item) for item in population]
    evaluated = evaluate_population(population, matching_context)
    assert [item[0] for item in evaluated] == [{"S1": "P1"}, {"S1": None}]
    assert population == snapshot
    assert all(item[0] is not original for item, original in zip(
        evaluate_population(population, matching_context),
        population,
        strict=True,
    ))


def test_equal_evaluation_scores_preserve_population_order() -> None:
    matching_context = context()
    population = [
        {"S1": None, "first-marker": None},
        {"S1": None, "second-marker": None},
    ]
    evaluated = evaluate_population(population, matching_context)
    assert list(evaluated[0][0])[-1] == "first-marker"
    assert list(evaluated[1][0])[-1] == "second-marker"


def test_empty_population_evaluation() -> None:
    assert evaluate_population([], context()) == []


def test_tournament_selects_sampled_entry() -> None:
    population = [scored({"S1": None}, 0), scored({"S1": "P1"}, 100)]
    selected = select_parent(population, 1, random.Random(1))
    assert selected in [item[0] for item in population]


def test_tournament_selects_best_and_returns_copy() -> None:
    best = {"S1": "P1"}
    population = [scored({"S1": None}, 0), scored(best, 100)]
    selected = select_parent(population, 2, random.Random(1))
    assert selected == best
    assert selected is not best


@pytest.mark.parametrize(
    ("population", "size"),
    [([], 1), ([scored({"S1": None}, 0)], 0), ([scored({"S1": None}, 0)], 2)],
)
def test_tournament_rejects_invalid_arguments(
    population: list[tuple[dict[str, str | None], float, ScoreBreakdown]],
    size: int,
) -> None:
    with pytest.raises(ValueError):
        select_parent(population, size, random.Random(1))


def test_crossover_preserves_order_uses_parent_genes_and_is_pure() -> None:
    parent_a = {"S2": "P1", "S1": None, "S3": "P2"}
    parent_b = {"S1": "P2", "S3": None, "S2": "P3"}
    snapshot_a = dict(parent_a)
    snapshot_b = dict(parent_b)
    child = crossover(parent_a, parent_b, random.Random(4))
    assert list(child) == list(parent_a)
    assert all(child[key] in (parent_a[key], parent_b[key]) for key in child)
    assert parent_a == snapshot_a
    assert parent_b == snapshot_b
    assert child is not parent_a and child is not parent_b


def test_crossover_rejects_mismatched_keys() -> None:
    with pytest.raises(ValueError, match="same student IDs"):
        crossover({"S1": None}, {"S2": None}, random.Random(1))


def test_zero_rate_mutation_preserves_values_in_new_dictionary() -> None:
    assignment = {"S1": "P1", "S2": None}
    mutated = mutate(
        assignment,
        {"S1": (None, "P1"), "S2": (None, "P2")},
        0,
        random.Random(1),
    )
    assert mutated == assignment
    assert mutated is not assignment


def test_full_rate_mutation_processes_all_genes_with_candidate_values() -> None:
    assignment = {"S1": "old", "S2": "old"}
    options = {"S1": ("P1",), "S2": (None,)}
    mutated = mutate(assignment, options, 1, random.Random(1))
    assert mutated == {"S1": "P1", "S2": None}
    assert all(value in options[key] for key, value in mutated.items())


@pytest.mark.parametrize("rate", [-0.1, 1.1])
def test_mutation_rejects_invalid_rate(rate: float) -> None:
    with pytest.raises(ValueError, match="mutation_rate"):
        mutate({"S1": None}, {"S1": (None,)}, rate, random.Random(1))


def test_mutation_rejects_missing_candidate_options() -> None:
    with pytest.raises(ValueError, match="S1"):
        mutate({"S1": None}, {}, 0.1, random.Random(1))


def test_mutation_rejects_empty_candidate_options() -> None:
    with pytest.raises(ValueError, match="S1"):
        mutate({"S1": None}, {"S1": ()}, 0.1, random.Random(1))


def test_mutation_is_seeded() -> None:
    assignment = {"S1": None, "S2": None}
    options = {"S1": (None, "P1"), "S2": (None, "P2")}
    assert mutate(assignment, options, 1, random.Random(9)) == mutate(
        assignment, options, 1, random.Random(9)
    )


def test_preserve_elites_returns_independent_top_copies() -> None:
    top = {"S1": "P1"}
    population = [scored(top, 100), scored({"S1": None}, 0)]
    elites = preserve_elites(population, 1)
    assert elites == [top]
    assert elites[0] is not top


def test_zero_elites() -> None:
    assert preserve_elites([scored({"S1": None}, 0)], 0) == []


@pytest.mark.parametrize("elite_count", [-1, 2])
def test_invalid_elite_count(elite_count: int) -> None:
    with pytest.raises(ValueError, match="elite_count"):
        preserve_elites([scored({"S1": None}, 0)], elite_count)


def test_all_project_positions_filled_exactly() -> None:
    matching_context = context(
        students=[student("S1"), student("S2"), student("S3")],
        projects=[project("P1", 2), project("P2", 1)],
    )
    assert all_project_positions_filled(
        {"S1": "P1", "S2": "P1", "S3": "P2"}, matching_context
    )


def test_all_positions_false_with_open_project_position() -> None:
    matching_context = context(
        students=[student("S1"), student("S2"), student("S3")],
        projects=[project("P1", 2), project("P2", 1)],
    )
    assert not all_project_positions_filled(
        {"S1": "P1", "S2": None, "S3": "P2"}, matching_context
    )


def test_all_positions_false_with_over_capacity_project() -> None:
    matching_context = context(
        students=[student("S1"), student("S2")],
        projects=[project("P1", 1)],
    )
    assert not all_project_positions_filled(
        {"S1": "P1", "S2": "P1"}, matching_context
    )


def test_ga_returns_consistent_reproducible_result() -> None:
    matching_context = context(target_score=90)
    options = build_candidate_options(matching_context)
    first = run_genetic_algorithm(matching_context, options, random.Random(12))
    second = run_genetic_algorithm(matching_context, options, random.Random(12))
    assert isinstance(first, GAResult)
    assert first == second
    assert first.generations >= 1
    assert set(first.assignment) == {"S1"}
    assert first.assignment["S1"] in options["S1"] or first.assignment["S1"] is None
    score, score_breakdown = calculate_fitness(
        first.assignment, matching_context
    )
    assert first.final_score == score
    assert first.score_breakdown == score_breakdown


def test_target_score_stops_on_initial_generation() -> None:
    matching_context = context(target_score=0)
    result = run_genetic_algorithm(
        matching_context,
        build_candidate_options(matching_context),
        random.Random(1),
    )
    assert result.stop_reason == TARGET_SCORE_REACHED
    assert result.generations == 1


def test_all_positions_filled_stopping() -> None:
    matching_context = context(
        students=[student("S1", level=0)],
        projects=[project(max_team_size=1, learning=True)],
        population_size=2,
        elite_count=0,
        tournament_size=1,
        target_score=90,
        allow_unassigned=False,
    )
    result = run_genetic_algorithm(
        matching_context,
        build_candidate_options(matching_context),
        random.Random(1),
    )
    assert result.stop_reason == ALL_POSITIONS_FILLED
    assert result.generations == 1


def test_patience_stopping() -> None:
    matching_context = context(
        students=[student("S1", level=0)],
        projects=[project(max_team_size=2, learning=True)],
        mutation_rate=0,
        target_score=100,
        patience=1,
        max_generations=5,
    )
    result = run_genetic_algorithm(
        matching_context,
        build_candidate_options(matching_context),
        random.Random(2),
    )
    assert result.stop_reason == NO_IMPROVEMENT
    assert result.generations == 2


def test_generation_limit_stopping_and_count() -> None:
    matching_context = context(
        students=[student("S1", level=0)],
        projects=[project(max_team_size=2, learning=True)],
        target_score=100,
        patience=0,
        max_generations=2,
    )
    result = run_genetic_algorithm(
        matching_context,
        build_candidate_options(matching_context),
        random.Random(3),
    )
    assert result.stop_reason == MAX_GENERATIONS
    assert result.generations == matching_context.config.max_generations


def test_global_best_is_not_replaced_by_worse_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_context = context(
        population_size=1,
        elite_count=0,
        tournament_size=1,
        target_score=100,
        max_generations=2,
    )
    evaluations = iter(
        [
            [scored({"S1": "P1"}, 80)],
            [scored({"S1": None}, 20)],
        ]
    )
    monkeypatch.setattr(
        ga_module, "evaluate_population", lambda population, ctx: next(evaluations)
    )
    result = run_genetic_algorithm(
        matching_context,
        build_candidate_options(matching_context),
        random.Random(1),
    )
    assert result.assignment == {"S1": "P1"}
    assert result.final_score == 80


def test_generated_children_are_repaired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_context = context(
        population_size=4,
        elite_count=1,
        tournament_size=2,
        target_score=100,
        max_generations=2,
    )
    options = build_candidate_options(matching_context)
    calls: list[dict[str, str | None]] = []
    original_repair = ga_module.repair_assignment

    def recording_repair(
        assignment: dict[str, str | None],
        ctx: MatchingContext,
        candidates: dict[str, tuple[str | None, ...]],
        rng: random.Random,
    ) -> dict[str, str | None]:
        calls.append(dict(assignment))
        return original_repair(assignment, ctx, candidates, rng)

    monkeypatch.setattr(ga_module, "repair_assignment", recording_repair)
    monkeypatch.setattr(
        ga_module,
        "evaluate_population",
        lambda population, ctx: [
            scored(dict(assignment), 10) for assignment in population
        ],
    )
    run_genetic_algorithm(matching_context, options, random.Random(1))
    assert len(calls) == matching_context.config.population_size - 1


@pytest.mark.parametrize("options", [{}, {"S1": ()}])
def test_ga_rejects_missing_or_empty_candidate_options(
    options: dict[str, tuple[str | None, ...]],
) -> None:
    with pytest.raises(ValueError, match="S1"):
        run_genetic_algorithm(context(), options, random.Random(1))
