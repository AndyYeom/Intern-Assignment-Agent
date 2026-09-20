import json
from pathlib import Path

from matching import (
    ALL_POSITIONS_FILLED,
    MAX_GENERATIONS,
    NO_IMPROVEMENT,
    TARGET_SCORE_REACHED,
    GAConfig,
    MatchingInput,
    MatchingOutput,
    build_candidate_options,
    hard_requirements_covered,
    load_matching_input,
    optimize_matching,
    optimize_matching_from_files,
    preprocess_inputs,
    save_matching_output,
    students_for_project,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRECTORY = REPOSITORY_ROOT / "src" / "matching" / "sources"


def source_paths() -> dict[str, Path]:
    return {
        "students": SOURCE_DIRECTORY / "students.json",
        "projects": SOURCE_DIRECTORY / "projects.json",
        "taxonomy": SOURCE_DIRECTORY / "taxonomy.json",
        "constraints": SOURCE_DIRECTORY / "constraints.json",
        "config": SOURCE_DIRECTORY / "ga_config.json",
    }


def load_source_input() -> MatchingInput:
    paths = source_paths()
    return load_matching_input(
        [paths["students"]],
        [paths["projects"]],
        paths["taxonomy"],
        paths["constraints"],
        paths["config"],
    )


def assert_feasible_output(data: MatchingInput, output: MatchingOutput) -> None:
    context = preprocess_inputs(data)
    candidate_options = build_candidate_options(context)
    assert list(output.assignments) == [
        student.student_id for student in data.students
    ]
    assert set(output.assignments.values()) <= {
        None,
        *(project.project_id for project in data.projects),
    }
    for project in data.projects:
        team = students_for_project(output.assignments, project.project_id)
        assert len(team) <= project.max_team_size
        if team:
            assert len(team) >= project.min_team_size
            assert hard_requirements_covered(team, project, context)
    for student_id, project_id in output.assignments.items():
        if project_id is not None:
            assert project_id in candidate_options[student_id]
    assert 0 <= output.final_score <= 100
    assert all(0 <= score <= 100 for score in output.score_breakdown.values())
    assert 1 <= output.generations <= data.config.max_generations
    assert output.stop_reason in {
        TARGET_SCORE_REACHED,
        ALL_POSITIONS_FILLED,
        NO_IMPROVEMENT,
        MAX_GENERATIONS,
    }


def test_real_source_files_load_and_produce_candidates() -> None:
    paths = source_paths()
    assert all(path.is_file() for path in paths.values())
    data = load_source_input()
    assert data.students
    assert data.projects
    assert data.taxonomy.nodes
    context = preprocess_inputs(data)
    candidate_options = build_candidate_options(context)
    assert list(candidate_options) == [
        student.student_id for student in data.students
    ]
    assert all(candidate_options.values())


def test_file_pipeline_returns_valid_matching_output() -> None:
    paths = source_paths()
    output = optimize_matching_from_files(
        [paths["students"]],
        [paths["projects"]],
        paths["taxonomy"],
        paths["constraints"],
        paths["config"],
    )
    assert isinstance(output, MatchingOutput)
    assert_feasible_output(load_source_input(), output)


def test_full_real_source_flow_is_reproducible_and_saves_sequentially(
    tmp_path: Path,
) -> None:
    data = load_source_input()
    data = data.model_copy(
        update={
            "config": GAConfig(
                population_size=10,
                max_generations=5,
                mutation_rate=data.config.mutation_rate,
                elite_count=2,
                tournament_size=3,
                target_score=data.config.target_score,
                patience=3,
                seed=42,
            )
        }
    )
    first = optimize_matching(data)
    second = optimize_matching(data)
    assert first == second
    assert_feasible_output(data, first)

    first_path = save_matching_output(first, tmp_path)
    first_content = first_path.read_text(encoding="utf-8")
    second_path = save_matching_output(second, tmp_path)
    assert first_path == tmp_path / "01.json"
    assert second_path == tmp_path / "02.json"
    assert first_path.read_text(encoding="utf-8") == first_content
    assert json.loads(first_content) == first.model_dump(mode="json")
    assert json.loads(second_path.read_text(encoding="utf-8")) == (
        second.model_dump(mode="json")
    )
