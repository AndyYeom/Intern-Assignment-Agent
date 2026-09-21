"""Public in-memory and file-based matching pipelines."""

import random
from collections.abc import Sequence
from pathlib import Path

from .artifacts import DEFAULT_ARTIFACT_DIRECTORY, save_matching_output
from .ga import GAResult, run_genetic_algorithm
from .preprocessing import (
    MatchingContext,
    load_matching_input,
    preprocess_inputs,
)
from .pruning import build_candidate_options
from .schemas import MatchingInput, MatchingOutput


def build_matching_output(
    ga_result: GAResult,
    context: MatchingContext,
) -> MatchingOutput:
    assignments = {
        student.student_id: ga_result.assignment.get(student.student_id)
        for student in context.students
    }
    assigned_project_ids = {
        project_id for project_id in assignments.values() if project_id is not None
    }

    return MatchingOutput.model_validate(
        {
            "assignments": assignments,
            "final_score": ga_result.final_score,
            "score_breakdown": dict(ga_result.score_breakdown),
            "unassigned_students": [
                student.student_id
                for student in context.students
                if assignments[student.student_id] is None
            ],
            "unassigned_projects": [
                project.project_id
                for project in context.projects
                if project.project_id not in assigned_project_ids
            ],
            "generations": ga_result.generations,
            "stop_reason": ga_result.stop_reason,
        }
    )


def optimize_matching(data: MatchingInput) -> MatchingOutput:
    context = preprocess_inputs(data)
    candidate_options = build_candidate_options(context)
    for student in context.students:
        if not candidate_options[student.student_id]:
            raise ValueError(
                f"Student '{student.student_id}' has no candidate project and "
                "unassigned assignments are disabled"
            )

    rng = random.Random(context.config.seed)
    ga_result = run_genetic_algorithm(
        context=context,
        candidate_options=candidate_options,
        rng=rng,
    )
    return build_matching_output(ga_result=ga_result, context=context)


def optimize_matching_from_files(
    student_paths: Sequence[str | Path],
    project_paths: Sequence[str | Path],
    taxonomy_path: str | Path,
    constraints_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> MatchingOutput:
    data = load_matching_input(
        student_paths=student_paths,
        project_paths=project_paths,
        taxonomy_path=taxonomy_path,
        constraints_path=constraints_path,
        config_path=config_path,
    )
    return optimize_matching(data)


def optimize_matching_and_save(
    data: MatchingInput,
    artifact_directory: str | Path = DEFAULT_ARTIFACT_DIRECTORY,
) -> tuple[MatchingOutput, Path]:
    output = optimize_matching(data)
    saved_path = save_matching_output(output, artifact_directory)
    return output, saved_path


def optimize_matching_from_files_and_save(
    student_paths: Sequence[str | Path],
    project_paths: Sequence[str | Path],
    taxonomy_path: str | Path,
    constraints_path: str | Path | None = None,
    config_path: str | Path | None = None,
    artifact_directory: str | Path = DEFAULT_ARTIFACT_DIRECTORY,
) -> tuple[MatchingOutput, Path]:
    output = optimize_matching_from_files(
        student_paths=student_paths,
        project_paths=project_paths,
        taxonomy_path=taxonomy_path,
        constraints_path=constraints_path,
        config_path=config_path,
    )
    saved_path = save_matching_output(output, artifact_directory)
    return output, saved_path
