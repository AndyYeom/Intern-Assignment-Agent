import json
from pathlib import Path

import pytest

import matching.artifacts as artifacts_module
import matching.pipeline as pipeline_module
from matching import (
    DEFAULT_ARTIFACT_DIRECTORY,
    GAConfig,
    MatchingInput,
    MatchingOutput,
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
    StudentSkill,
    TaxonomyNode,
    TaxonomyTree,
    format_artifact_filename,
    get_next_artifact_index,
    optimize_matching,
    optimize_matching_and_save,
    optimize_matching_from_files,
    optimize_matching_from_files_and_save,
    save_matching_output,
)


def output() -> MatchingOutput:
    return MatchingOutput(
        assignments={"S1": "P1", "S2": None},
        final_score=82.5,
        score_breakdown={
            "assigned_student_score": 85.0,
            "growth_score": 70.0,
            "team_coverage_score": 90.0,
            "utilization_score": 80.0,
        },
        unassigned_students=["S2"],
        unassigned_projects=[],
        generations=25,
        stop_reason="no_improvement",
    )


def matching_input() -> MatchingInput:
    return MatchingInput(
        students=[
            StudentProfile(
                student_id="S1",
                name="Student",
                skills=[StudentSkill(skill_id="python", level=4)],
            )
        ],
        projects=[
            ProjectProfile(
                project_id="P1",
                name="Project",
                requirements=[
                    ProjectSkillRequirement(
                        skill_id="python",
                        required_level=4,
                        requirement_type=RequirementType.PREFERRED,
                    )
                ],
            )
        ],
        taxonomy=TaxonomyTree(
            nodes=[TaxonomyNode(skill_id="python", name="Python")]
        ),
        config=GAConfig(
            population_size=4,
            max_generations=2,
            mutation_rate=0.1,
            elite_count=1,
            tournament_size=2,
            target_score=90,
            patience=1,
            seed=42,
        ),
    )


def write_json(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (1, "01.json"),
        (9, "09.json"),
        (10, "10.json"),
        (99, "99.json"),
        (100, "100.json"),
    ],
)
def test_formats_artifact_filename(index: int, expected: str) -> None:
    assert format_artifact_filename(index) == expected


@pytest.mark.parametrize("index", [0, -1])
def test_rejects_nonpositive_artifact_index(index: int) -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        format_artifact_filename(index)


def test_default_artifact_directory_is_beside_module() -> None:
    expected = Path(artifacts_module.__file__).resolve().parent / "artifacts"
    assert DEFAULT_ARTIFACT_DIRECTORY == expected


def test_missing_artifact_directory_starts_at_one(tmp_path: Path) -> None:
    assert get_next_artifact_index(tmp_path / "missing") == 1


def test_empty_artifact_directory_starts_at_one(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    directory.mkdir()
    assert get_next_artifact_index(directory) == 1


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["01.json"], 2),
        (["01.json", "02.json"], 3),
        (["01.json", "05.json"], 6),
    ],
)
def test_next_index_uses_highest_numeric_json(
    tmp_path: Path,
    names: list[str],
    expected: int,
) -> None:
    for name in names:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert get_next_artifact_index(tmp_path) == expected


def test_next_index_ignores_non_artifact_files(tmp_path: Path) -> None:
    for name in (
        "notes.json",
        "result.json",
        "01.txt",
        "abc.json",
        ".DS_Store",
        "README.md",
    ):
        (tmp_path / name).write_text("ignored", encoding="utf-8")
    assert get_next_artifact_index(tmp_path) == 1


def test_save_creates_directory_and_first_sequential_file(tmp_path: Path) -> None:
    directory = tmp_path / "nested" / "artifacts"
    saved_path = save_matching_output(output(), directory)
    assert saved_path == directory / "01.json"
    assert saved_path.is_file()


def test_repeated_saves_create_sequential_files_without_overwrite(
    tmp_path: Path,
) -> None:
    first = save_matching_output(output(), tmp_path)
    first_content = first.read_text(encoding="utf-8")
    second = save_matching_output(output(), tmp_path)
    assert first.name == "01.json"
    assert second.name == "02.json"
    assert first.read_text(encoding="utf-8") == first_content


def test_save_retries_if_calculated_target_already_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = tmp_path / "01.json"
    existing.write_text("original", encoding="utf-8")
    monkeypatch.setattr(artifacts_module, "get_next_artifact_index", lambda _: 1)
    saved_path = save_matching_output(output(), tmp_path)
    assert saved_path == tmp_path / "02.json"
    assert existing.read_text(encoding="utf-8") == "original"


def test_saved_content_is_exact_valid_json_with_null_unicode_and_newline(
    tmp_path: Path,
) -> None:
    result = output().model_copy(update={"stop_reason": "完成"})
    saved_path = save_matching_output(result, tmp_path)
    raw = saved_path.read_text(encoding="utf-8")
    assert json.loads(raw) == result.model_dump(mode="json")
    assert json.loads(raw)["assignments"]["S2"] is None
    assert "完成" in raw
    assert raw.endswith("\n")


def test_optimize_and_save_returns_output_and_one_path(tmp_path: Path) -> None:
    result, saved_path = optimize_matching_and_save(matching_input(), tmp_path)
    assert isinstance(result, MatchingOutput)
    assert saved_path == tmp_path / "01.json"
    assert list(tmp_path.glob("*.json")) == [saved_path]
    assert json.loads(saved_path.read_text(encoding="utf-8")) == (
        result.model_dump(mode="json")
    )


def test_repeated_optimize_and_save_uses_next_filename(tmp_path: Path) -> None:
    first = optimize_matching_and_save(matching_input(), tmp_path)
    second = optimize_matching_and_save(matching_input(), tmp_path)
    assert first[1].name == "01.json"
    assert second[1].name == "02.json"
    assert first[0] == second[0]


def test_optimize_from_files_and_save(tmp_path: Path) -> None:
    data = matching_input()
    inputs = tmp_path / "inputs"
    artifacts = tmp_path / "artifacts"
    inputs.mkdir()
    student_path = write_json(
        inputs, "student.json", data.students[0].model_dump()
    )
    project_path = write_json(
        inputs, "project.json", data.projects[0].model_dump()
    )
    taxonomy_path = write_json(
        inputs, "taxonomy.json", data.taxonomy.model_dump()
    )
    config_path = write_json(inputs, "config.json", data.config.model_dump())
    result, saved_path = optimize_matching_from_files_and_save(
        [student_path],
        [project_path],
        taxonomy_path,
        config_path=config_path,
        artifact_directory=artifacts,
    )
    assert isinstance(result, MatchingOutput)
    assert saved_path == artifacts / "01.json"
    assert json.loads(saved_path.read_text(encoding="utf-8")) == (
        result.model_dump(mode="json")
    )


def test_in_memory_optimize_does_not_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_save(*args: object, **kwargs: object) -> None:
        raise AssertionError("save_matching_output must not be called")

    monkeypatch.setattr(pipeline_module, "save_matching_output", unexpected_save)
    assert isinstance(optimize_matching(matching_input()), MatchingOutput)


def test_file_optimize_does_not_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = matching_input()
    student_path = write_json(
        tmp_path, "student.json", data.students[0].model_dump()
    )
    project_path = write_json(
        tmp_path, "project.json", data.projects[0].model_dump()
    )
    taxonomy_path = write_json(
        tmp_path, "taxonomy.json", data.taxonomy.model_dump()
    )
    config_path = write_json(tmp_path, "config.json", data.config.model_dump())

    def unexpected_save(*args: object, **kwargs: object) -> None:
        raise AssertionError("save_matching_output must not be called")

    monkeypatch.setattr(pipeline_module, "save_matching_output", unexpected_save)
    result = optimize_matching_from_files(
        [student_path],
        [project_path],
        taxonomy_path,
        config_path=config_path,
    )
    assert isinstance(result, MatchingOutput)
