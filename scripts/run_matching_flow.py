"""Run the complete matching flow against the repository's source fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from matching import (
    ALL_POSITIONS_FILLED,
    MAX_GENERATIONS,
    NO_IMPROVEMENT,
    TARGET_SCORE_REACHED,
    MatchingInput,
    MatchingOutput,
    build_candidate_options,
    hard_requirements_covered,
    load_matching_input,
    optimize_matching,
    preprocess_inputs,
    save_matching_output,
    students_for_project,
)
from matching.preprocessing import MatchingContext

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = REPOSITORY_ROOT / "src" / "matching" / "sources"
ARTIFACT_DIRECTORY = REPOSITORY_ROOT / "src" / "matching" / "artifacts"


def _source_paths() -> dict[str, Path]:
    return {
        "students": SOURCE_DIRECTORY / "students.json",
        "projects": SOURCE_DIRECTORY / "projects.json",
        "taxonomy": SOURCE_DIRECTORY / "taxonomy.json",
        "constraints": SOURCE_DIRECTORY / "constraints.json",
        "config": SOURCE_DIRECTORY / "ga_config.json",
    }


def _validate_result(
    data: MatchingInput,
    context: MatchingContext,
    candidate_options: dict[str, tuple[str | None, ...]],
    output: MatchingOutput,
) -> None:
    student_ids = [student.student_id for student in data.students]
    project_ids = {project.project_id for project in data.projects}
    if list(output.assignments) != student_ids:
        raise AssertionError("Output assignments do not contain each student in order")
    if any(
        project_id is not None and project_id not in project_ids
        for project_id in output.assignments.values()
    ):
        raise AssertionError("Output contains an unknown project assignment")

    expected_unassigned_students = [
        student_id
        for student_id in student_ids
        if output.assignments[student_id] is None
    ]
    if output.unassigned_students != expected_unassigned_students:
        raise AssertionError("Unassigned student list does not match assignments")
    expected_unassigned_projects = [
        project.project_id
        for project in data.projects
        if project.project_id not in output.assignments.values()
    ]
    if output.unassigned_projects != expected_unassigned_projects:
        raise AssertionError("Unassigned project list does not match assignments")
    if not 0 <= output.final_score <= 100:
        raise AssertionError("Final score is outside 0 to 100")
    if any(not 0 <= score <= 100 for score in output.score_breakdown.values()):
        raise AssertionError("A score component is outside 0 to 100")
    if not 1 <= output.generations <= data.config.max_generations:
        raise AssertionError("Generation count is outside the configured range")
    if output.stop_reason not in {
        TARGET_SCORE_REACHED,
        ALL_POSITIONS_FILLED,
        NO_IMPROVEMENT,
        MAX_GENERATIONS,
    }:
        raise AssertionError("Unsupported GA stop reason")

    for project in data.projects:
        team = students_for_project(output.assignments, project.project_id)
        if len(team) > project.max_team_size:
            raise AssertionError(f"Project '{project.project_id}' exceeds maximum size")
        if team and len(team) < project.min_team_size:
            raise AssertionError(
                f"Project '{project.project_id}' is below minimum size"
            )
        if team and not hard_requirements_covered(team, project, context):
            raise AssertionError(
                f"Project '{project.project_id}' has uncovered hard requirements"
            )

    for student_id, project_id in output.assignments.items():
        if project_id is not None and project_id not in candidate_options[student_id]:
            raise AssertionError(
                f"Assignment {student_id} -> {project_id} is not a candidate option"
            )


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPOSITORY_ROOT))
    except ValueError:
        return str(path)


def _print_result(output: MatchingOutput) -> None:
    print(f"Final score: {output.final_score:.2f}")
    print(
        "Assigned student score: "
        f"{output.score_breakdown['assigned_student_score']:.2f}"
    )
    print(f"Growth score: {output.score_breakdown['growth_score']:.2f}")
    print(
        "Team coverage score: "
        f"{output.score_breakdown['team_coverage_score']:.2f}"
    )
    print(f"Utilization score: {output.score_breakdown['utilization_score']:.2f}")
    print("\nAssignments:")
    for student_id, project_id in output.assignments.items():
        print(f"{student_id} -> {project_id or 'UNASSIGNED'}")
    print("\nUnassigned students:")
    if output.unassigned_students:
        for student_id in output.unassigned_students:
            print(f"- {student_id}")
    else:
        print("- None")
    print("\nUnassigned projects:")
    if output.unassigned_projects:
        for project_id in output.unassigned_projects:
            print(f"- {project_id}")
    else:
        print("- None")


def run(seed: int | None, no_save: bool) -> int:
    paths = _source_paths()
    print("=== Student-Project Matching Flow ===\n")
    print("[1/7] Loading input JSON files")
    data = load_matching_input(
        student_paths=[paths["students"]],
        project_paths=[paths["projects"]],
        taxonomy_path=paths["taxonomy"],
        constraints_path=paths["constraints"],
        config_path=paths["config"],
    )
    if seed is not None:
        data = data.model_copy(
            update={"config": data.config.model_copy(update={"seed": seed})}
        )
    print(f"Students loaded: {len(data.students)}")
    print(f"Projects loaded: {len(data.projects)}")
    print(f"Taxonomy nodes loaded: {len(data.taxonomy.nodes)}")

    print("\n[2/7] Preprocessing")
    context = preprocess_inputs(data)
    print(f"Student lookup entries: {len(context.students_by_id)}")
    print(f"Project lookup entries: {len(context.projects_by_id)}")

    print("\n[3/7] Candidate pruning")
    candidate_options = build_candidate_options(context)
    for student_id, options in candidate_options.items():
        formatted = ", ".join(
            "None" if option is None else option for option in options
        )
        print(f"{student_id}: {formatted}")

    print("\n[4/7] Running genetic algorithm")
    print(f"Population size: {data.config.population_size}")
    print(f"Maximum generations: {data.config.max_generations}")
    print(f"Seed: {data.config.seed}")
    output = optimize_matching(data)

    print("\n[5/7] Optimization completed")
    print(f"Stop reason: {output.stop_reason}")
    print(f"Generations: {output.generations}")

    _validate_result(data, context, candidate_options, output)
    print("End-to-end validation passed")

    print("\n[6/7] Final result")
    _print_result(output)

    print("\n[7/7] Artifact")
    if no_save:
        print("Saving skipped (--no-save)")
        return 0

    saved_path = save_matching_output(output, ARTIFACT_DIRECTORY)
    saved_data = json.loads(saved_path.read_text(encoding="utf-8"))
    if saved_data != output.model_dump(mode="json"):
        raise AssertionError(f"Saved artifact does not match output: {saved_path}")
    print(f"Saved to: {_display_path(saved_path)}")
    print("Artifact verification passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run student-project matching with repository source fixtures."
    )
    parser.add_argument("--no-save", action="store_true", help="Do not save JSON")
    parser.add_argument("--seed", type=int, help="Override the configured GA seed")
    arguments = parser.parse_args()
    try:
        return run(seed=arguments.seed, no_save=arguments.no_save)
    except Exception as exc:
        print(f"Matching flow failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
