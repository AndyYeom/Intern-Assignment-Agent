import json
from pathlib import Path

import pytest

from matching import (
    ALL_POSITIONS_FILLED,
    MAX_GENERATIONS,
    NO_IMPROVEMENT,
    TARGET_SCORE_REACHED,
    GAConfig,
    GAResult,
    MatchingConstraints,
    MatchingInput,
    MatchingOutput,
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
    StudentSkill,
    TaxonomyNode,
    TaxonomyTree,
    build_candidate_options,
    build_matching_output,
    hard_requirements_covered,
    optimize_matching,
    optimize_matching_from_files,
    preprocess_inputs,
    students_for_project,
)


def skill(skill_id: str, level: int) -> StudentSkill:
    return StudentSkill(skill_id=skill_id, level=level)


def student(
    student_id: str,
    skills: list[StudentSkill],
) -> StudentProfile:
    return StudentProfile(student_id=student_id, name=student_id, skills=skills)


def requirement(
    skill_id: str,
    level: int,
    requirement_type: RequirementType,
    importance: float = 1.0,
) -> ProjectSkillRequirement:
    return ProjectSkillRequirement(
        skill_id=skill_id,
        required_level=level,
        requirement_type=requirement_type,
        importance=importance,
    )


def project(
    project_id: str,
    requirements: list[ProjectSkillRequirement],
    min_team_size: int,
    max_team_size: int,
) -> ProjectProfile:
    return ProjectProfile(
        project_id=project_id,
        name=project_id,
        min_team_size=min_team_size,
        max_team_size=max_team_size,
        requirements=requirements,
    )


def taxonomy() -> TaxonomyTree:
    return TaxonomyTree(
        nodes=[
            TaxonomyNode(skill_id="technology", name="Technology"),
            TaxonomyNode(
                skill_id="programming",
                name="Programming",
                parent_id="technology",
            ),
            TaxonomyNode(
                skill_id="python", name="Python", parent_id="programming"
            ),
            TaxonomyNode(
                skill_id="javascript",
                name="JavaScript",
                parent_id="programming",
            ),
            TaxonomyNode(
                skill_id="data", name="Data", parent_id="technology"
            ),
            TaxonomyNode(skill_id="sql", name="SQL", parent_id="data"),
        ]
    )


def matching_input(
    *,
    allow_unassigned: bool = True,
    seed: int = 17,
) -> MatchingInput:
    students = [
        student("S3", [skill("javascript", 3)]),
        student("S1", [skill("python", 4)]),
        student("S4", [skill("sql", 2)]),
        student("S2", [skill("python", 1)]),
    ]
    projects = [
        project(
            "P2",
            [
                requirement("sql", 2, RequirementType.HARD_REQUIREMENT),
                requirement("python", 3, RequirementType.PREFERRED),
            ],
            min_team_size=1,
            max_team_size=2,
        ),
        project(
            "P1",
            [
                requirement("python", 3, RequirementType.PREFERRED),
                requirement(
                    "javascript", 4, RequirementType.LEARNING_OPPORTUNITY
                ),
            ],
            min_team_size=2,
            max_team_size=3,
        ),
    ]
    return MatchingInput(
        students=students,
        projects=projects,
        taxonomy=taxonomy(),
        constraints=MatchingConstraints(
            minimum_lca_depth=1,
            allow_unassigned=allow_unassigned,
        ),
        config=GAConfig(
            population_size=6,
            max_generations=5,
            mutation_rate=0.2,
            elite_count=1,
            tournament_size=2,
            target_score=95,
            patience=2,
            seed=seed,
        ),
    )


def assert_output_invariants(data: MatchingInput, output: MatchingOutput) -> None:
    context = preprocess_inputs(data)
    candidate_options = build_candidate_options(context)
    assert list(output.assignments) == [item.student_id for item in data.students]
    assert set(output.assignments.values()) <= {
        None,
        *(item.project_id for item in data.projects),
    }
    assert output.unassigned_students == [
        item.student_id
        for item in data.students
        if output.assignments[item.student_id] is None
    ]
    assert output.unassigned_projects == [
        item.project_id
        for item in data.projects
        if item.project_id not in output.assignments.values()
    ]
    assert 0 <= output.final_score <= 100
    assert set(output.score_breakdown) == {
        "assigned_student_score",
        "growth_score",
        "team_coverage_score",
        "utilization_score",
    }
    assert all(0 <= score <= 100 for score in output.score_breakdown.values())
    assert 1 <= output.generations <= data.config.max_generations
    assert output.stop_reason in {
        TARGET_SCORE_REACHED,
        ALL_POSITIONS_FILLED,
        NO_IMPROVEMENT,
        MAX_GENERATIONS,
    }

    for work in data.projects:
        team = students_for_project(output.assignments, work.project_id)
        assert len(team) <= work.max_team_size
        if team:
            assert len(team) >= work.min_team_size
            assert hard_requirements_covered(team, work, context)
    for student_id, project_id in output.assignments.items():
        if project_id is not None:
            assert project_id in candidate_options[student_id]


def write_json(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_optimize_matching_returns_complete_valid_output() -> None:
    data = matching_input()
    output = optimize_matching(data)
    assert isinstance(output, MatchingOutput)
    assert_output_invariants(data, output)


def test_optimize_matching_is_reproducible() -> None:
    first = optimize_matching(matching_input(seed=23))
    second = optimize_matching(matching_input(seed=23))
    assert first == second


def test_optimize_matching_does_not_mutate_input() -> None:
    data = matching_input()
    snapshot = data.model_dump()
    optimize_matching(data)
    assert data.model_dump() == snapshot


def test_unmatched_student_is_unassigned_when_allowed() -> None:
    data = MatchingInput(
        students=[student("S1", [skill("unknown", 3)])],
        projects=[
            project(
                "P1",
                [requirement("python", 3, RequirementType.PREFERRED)],
                1,
                1,
            )
        ],
        taxonomy=taxonomy(),
        config=GAConfig(
            population_size=4,
            max_generations=2,
            elite_count=1,
            tournament_size=2,
            patience=1,
        ),
    )
    output = optimize_matching(data)
    assert output.assignments == {"S1": None}
    assert output.unassigned_students == ["S1"]
    assert output.unassigned_projects == ["P1"]


def test_empty_candidate_set_is_rejected_with_student_id() -> None:
    data = MatchingInput(
        students=[student("S-missing", [skill("unknown", 3)])],
        projects=[
            project(
                "P1",
                [requirement("python", 3, RequirementType.PREFERRED)],
                1,
                1,
            )
        ],
        taxonomy=taxonomy(),
        constraints=MatchingConstraints(allow_unassigned=False),
    )
    with pytest.raises(ValueError, match="S-missing"):
        optimize_matching(data)


def test_build_matching_output_copies_and_normalizes_internal_data() -> None:
    data = matching_input()
    context = preprocess_inputs(data)
    internal_assignment = {
        "unknown": "P1",
        "S3": "P1",
        "S1": None,
        "S4": "P2",
        "S2": None,
    }
    internal_breakdown = {
        "assigned_student_score": 50.0,
        "growth_score": 60.0,
        "team_coverage_score": 70.0,
        "utilization_score": 80.0,
    }
    result = GAResult(
        assignment=internal_assignment,
        final_score=62.0,
        score_breakdown=internal_breakdown,
        generations=3,
        stop_reason=MAX_GENERATIONS,
    )

    output = build_matching_output(result, context)

    assert list(output.assignments) == ["S3", "S1", "S4", "S2"]
    assert "unknown" not in output.assignments
    assert output.unassigned_students == ["S1", "S2"]
    assert output.unassigned_projects == []
    internal_assignment["S3"] = None
    internal_breakdown["growth_score"] = 0
    assert output.assignments["S3"] == "P1"
    assert output.score_breakdown["growth_score"] == 60


def test_unassigned_projects_preserve_order_and_exclude_active_projects() -> None:
    data = matching_input()
    context = preprocess_inputs(data)
    result = GAResult(
        assignment={"S3": None, "S1": "P1", "S4": None, "S2": None},
        final_score=50,
        score_breakdown={
            "assigned_student_score": 50,
            "growth_score": 50,
            "team_coverage_score": 50,
            "utilization_score": 50,
        },
        generations=1,
        stop_reason=MAX_GENERATIONS,
    )
    output = build_matching_output(result, context)
    assert output.unassigned_projects == ["P2"]


def test_file_pipeline_supports_multiple_files_and_custom_settings(
    tmp_path: Path,
) -> None:
    data = matching_input(seed=31)
    student_paths = [
        write_json(
            tmp_path,
            "students-a.json",
            [item.model_dump() for item in data.students[:2]],
        ),
        write_json(
            tmp_path,
            "students-b.json",
            {"students": [item.model_dump() for item in data.students[2:]]},
        ),
    ]
    project_paths = [
        write_json(tmp_path, "projects-a.json", data.projects[0].model_dump()),
        write_json(
            tmp_path,
            "projects-b.json",
            [data.projects[1].model_dump()],
        ),
    ]
    taxonomy_path = write_json(
        tmp_path, "taxonomy.json", data.taxonomy.model_dump()
    )
    constraints_path = write_json(
        tmp_path, "constraints.json", data.constraints.model_dump()
    )
    config_path = write_json(tmp_path, "config.json", data.config.model_dump())

    from_files = optimize_matching_from_files(
        student_paths,
        project_paths,
        taxonomy_path,
        constraints_path,
        config_path,
    )
    in_memory = optimize_matching(data)
    assert from_files == in_memory
    assert list(from_files.assignments) == ["S3", "S1", "S4", "S2"]
    assert_output_invariants(data, from_files)


def test_file_pipeline_supports_default_constraints_and_config(
    tmp_path: Path,
) -> None:
    learner = student("S1", [skill("python", 4)])
    work = project(
        "P1",
        [requirement("python", 4, RequirementType.PREFERRED)],
        1,
        1,
    )
    students_path = write_json(tmp_path, "student.json", learner.model_dump())
    projects_path = write_json(tmp_path, "project.json", work.model_dump())
    taxonomy_path = write_json(
        tmp_path,
        "taxonomy.json",
        {"nodes": [TaxonomyNode(skill_id="python", name="Python").model_dump()]},
    )
    output = optimize_matching_from_files(
        [students_path], [projects_path], taxonomy_path
    )
    assert isinstance(output, MatchingOutput)
    assert output.assignments == {"S1": "P1"}


def test_end_to_end_json_flow_is_feasible_and_reproducible(tmp_path: Path) -> None:
    data = matching_input(seed=43)
    students_path = write_json(
        tmp_path,
        "students.json",
        {"students": [item.model_dump() for item in data.students]},
    )
    projects_path = write_json(
        tmp_path,
        "projects.json",
        {"projects": [item.model_dump() for item in data.projects]},
    )
    taxonomy_path = write_json(
        tmp_path, "taxonomy.json", data.taxonomy.model_dump()
    )
    constraints_path = write_json(
        tmp_path, "constraints.json", data.constraints.model_dump()
    )
    config_path = write_json(tmp_path, "config.json", data.config.model_dump())

    first = optimize_matching_from_files(
        [students_path],
        [projects_path],
        taxonomy_path,
        constraints_path,
        config_path,
    )
    second = optimize_matching_from_files(
        [students_path],
        [projects_path],
        taxonomy_path,
        constraints_path,
        config_path,
    )
    assert first == second
    assert_output_invariants(data, first)
