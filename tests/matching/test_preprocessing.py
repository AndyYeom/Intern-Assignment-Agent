import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from matching import (
    GAConfig,
    MatchingConstraints,
    ProjectProfile,
    StudentProfile,
    load_config_file,
    load_constraints_file,
    load_matching_input,
    load_project_files,
    load_student_files,
    load_taxonomy_file,
    preprocess_inputs,
)


def write_json(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def student(student_id: str, name: str | None = None) -> dict[str, object]:
    return {
        "student_id": student_id,
        "name": name or f"Student {student_id}",
        "skills": [],
    }


def project(project_id: str, name: str | None = None) -> dict[str, object]:
    return {
        "project_id": project_id,
        "name": name or f"Project {project_id}",
        "requirements": [],
    }


def taxonomy_nodes() -> list[dict[str, object]]:
    return [
        {"skill_id": "technology", "name": "Technology", "parent_id": None},
        {
            "skill_id": "python",
            "name": "Python",
            "parent_id": "technology",
        },
    ]


def valid_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        write_json(tmp_path, "students.json", student("S1")),
        write_json(tmp_path, "projects.json", project("P1")),
        write_json(tmp_path, "taxonomy.json", taxonomy_nodes()),
    )


def test_loads_multiple_single_student_files_in_order(tmp_path: Path) -> None:
    paths = [
        write_json(tmp_path, "second.json", student("S2")),
        write_json(tmp_path, "first.json", student("S1")),
    ]
    assert [item.student_id for item in load_student_files(paths)] == ["S2", "S1"]


def test_loads_multiple_single_project_files_in_order(tmp_path: Path) -> None:
    paths = [
        write_json(tmp_path, "second.json", project("P2")),
        write_json(tmp_path, "first.json", project("P1")),
    ]
    assert [item.project_id for item in load_project_files(paths)] == ["P2", "P1"]


@pytest.mark.parametrize("wrapped", [False, True])
def test_loads_raw_or_wrapped_student_list(
    tmp_path: Path, wrapped: bool
) -> None:
    records = [student("S2"), student("S1")]
    value: object = {"students": records} if wrapped else records
    path = write_json(tmp_path, "students.json", value)
    assert [item.student_id for item in load_student_files([path])] == ["S2", "S1"]


@pytest.mark.parametrize("wrapped", [False, True])
def test_loads_raw_or_wrapped_project_list(
    tmp_path: Path, wrapped: bool
) -> None:
    records = [project("P2"), project("P1")]
    value: object = {"projects": records} if wrapped else records
    path = write_json(tmp_path, "projects.json", value)
    assert [item.project_id for item in load_project_files([path])] == ["P2", "P1"]


def test_mixes_all_supported_student_shapes(tmp_path: Path) -> None:
    paths = [
        write_json(tmp_path, "single.json", student("S1")),
        write_json(tmp_path, "raw.json", [student("S2"), student("S3")]),
        write_json(
            tmp_path, "wrapped.json", {"students": [student("S4"), student("S5")]}
        ),
    ]
    assert [item.student_id for item in load_student_files(paths)] == [
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
    ]


def test_mixes_all_supported_project_shapes(tmp_path: Path) -> None:
    paths = [
        write_json(tmp_path, "single.json", project("P1")),
        write_json(tmp_path, "raw.json", [project("P2"), project("P3")]),
        write_json(
            tmp_path, "wrapped.json", {"projects": [project("P4"), project("P5")]}
        ),
    ]
    assert [item.project_id for item in load_project_files(paths)] == [
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
    ]


@pytest.mark.parametrize("loader", [load_student_files, load_project_files])
def test_rejects_empty_path_sequence(
    loader: Callable[[Sequence[str | Path]], object],
) -> None:
    with pytest.raises(ValueError, match="At least one"):
        loader([])


def test_rejects_duplicate_student_ids_across_files(tmp_path: Path) -> None:
    first = write_json(tmp_path, "first.json", student("S1"))
    second = write_json(tmp_path, "second.json", student("S1"))
    with pytest.raises(ValueError, match=r"S1.*second\.json.*first\.json"):
        load_student_files([first, second])


def test_rejects_duplicate_project_ids_across_files(tmp_path: Path) -> None:
    first = write_json(tmp_path, "first.json", project("P1"))
    second = write_json(tmp_path, "second.json", project("P1"))
    with pytest.raises(ValueError, match=r"P1.*second\.json.*first\.json"):
        load_project_files([first, second])


def test_rejects_malformed_json_with_path(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match=str(path)) as error:
        load_student_files([path])
    assert isinstance(error.value.__cause__, json.JSONDecodeError)


def test_rejects_missing_file_with_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match=str(path)):
        load_student_files([path])


def test_rejects_directory_with_path(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError, match=str(tmp_path)):
        load_student_files([tmp_path])


@pytest.mark.parametrize("value", ["students", 1, True, None])
def test_rejects_scalar_record_roots(tmp_path: Path, value: object) -> None:
    path = write_json(tmp_path, "students.json", value)
    with pytest.raises(ValueError, match=str(path)):
        load_student_files([path])


@pytest.mark.parametrize("wrapped", [False, True])
def test_rejects_empty_record_lists(tmp_path: Path, wrapped: bool) -> None:
    value: object = {"students": []} if wrapped else []
    path = write_json(tmp_path, "students.json", value)
    with pytest.raises(ValueError, match=str(path)):
        load_student_files([path])


def test_rejects_non_list_wrapper(tmp_path: Path) -> None:
    path = write_json(tmp_path, "students.json", {"students": student("S1")})
    with pytest.raises(ValueError, match=str(path)):
        load_student_files([path])


def test_student_validation_error_has_path_and_index(tmp_path: Path) -> None:
    path = write_json(tmp_path, "students.json", [student("S1"), {"name": "Bad"}])
    with pytest.raises(ValueError, match=rf"{path} at index 1") as error:
        load_student_files([path])
    assert error.value.__cause__ is not None


def test_project_validation_error_has_path_and_index(tmp_path: Path) -> None:
    path = write_json(tmp_path, "projects.json", [project("P1"), {"name": "Bad"}])
    with pytest.raises(ValueError, match=rf"{path} at index 1") as error:
        load_project_files([path])
    assert error.value.__cause__ is not None


@pytest.mark.parametrize("wrapped", [False, True])
def test_loads_raw_or_wrapped_taxonomy(tmp_path: Path, wrapped: bool) -> None:
    nodes = taxonomy_nodes()
    value: object = {"nodes": nodes} if wrapped else nodes
    path = write_json(tmp_path, "taxonomy.json", value)
    tree = load_taxonomy_file(path)
    assert [node.skill_id for node in tree.nodes] == ["technology", "python"]


def test_rejects_single_unwrapped_taxonomy_node(tmp_path: Path) -> None:
    path = write_json(tmp_path, "taxonomy.json", taxonomy_nodes()[0])
    with pytest.raises(ValueError, match=str(path)):
        load_taxonomy_file(path)


def test_taxonomy_validation_error_has_path(tmp_path: Path) -> None:
    path = write_json(
        tmp_path,
        "taxonomy.json",
        [{"skill_id": "python", "name": "Python", "parent_id": "missing"}],
    )
    with pytest.raises(ValueError, match=str(path)) as error:
        load_taxonomy_file(path)
    assert error.value.__cause__ is not None


def test_optional_files_use_defaults() -> None:
    assert load_constraints_file(None) == MatchingConstraints()
    assert load_config_file(None) == GAConfig()


def test_loads_custom_constraints(tmp_path: Path) -> None:
    path = write_json(
        tmp_path,
        "constraints.json",
        {"minimum_lca_depth": 3, "allow_unassigned": False},
    )
    assert load_constraints_file(path) == MatchingConstraints(
        minimum_lca_depth=3, allow_unassigned=False
    )


def test_loads_custom_ga_config(tmp_path: Path) -> None:
    path = write_json(
        tmp_path,
        "config.json",
        {"population_size": 20, "elite_count": 2, "tournament_size": 4},
    )
    assert load_config_file(path).population_size == 20


@pytest.mark.parametrize(
    ("loader", "filename"),
    [(load_constraints_file, "constraints.json"), (load_config_file, "config.json")],
)
def test_optional_object_files_reject_non_object_root(
    tmp_path: Path,
    loader: Callable[[str | Path | None], object],
    filename: str,
) -> None:
    path = write_json(tmp_path, filename, [])
    with pytest.raises(ValueError, match=str(path)):
        loader(path)


def test_builds_complete_matching_input(tmp_path: Path) -> None:
    students, projects, taxonomy = valid_paths(tmp_path)
    constraints = write_json(
        tmp_path, "constraints.json", {"minimum_lca_depth": 2}
    )
    config = write_json(
        tmp_path,
        "config.json",
        {"population_size": 10, "elite_count": 1, "tournament_size": 2},
    )
    data = load_matching_input(
        [students], [projects], taxonomy, constraints, config
    )
    assert data.students[0].student_id == "S1"
    assert data.projects[0].project_id == "P1"
    assert data.constraints.minimum_lca_depth == 2
    assert data.config.population_size == 10


def test_preprocesses_ordered_immutable_context(tmp_path: Path) -> None:
    students = write_json(
        tmp_path, "students.json", [student("S2"), student("S1")]
    )
    projects = write_json(
        tmp_path, "projects.json", [project("P2"), project("P1")]
    )
    taxonomy = write_json(tmp_path, "taxonomy.json", taxonomy_nodes())
    data = load_matching_input([students], [projects], taxonomy)

    context = preprocess_inputs(data)

    assert tuple(item.student_id for item in context.students) == ("S2", "S1")
    assert tuple(item.project_id for item in context.projects) == ("P2", "P1")
    assert context.students_by_id == {
        "S2": data.students[0],
        "S1": data.students[1],
    }
    assert context.projects_by_id == {
        "P2": data.projects[0],
        "P1": data.projects[1],
    }
    assert context.taxonomy_nodes_by_id["python"].name == "Python"
    assert context.taxonomy_parent_by_id == {
        "technology": None,
        "python": "technology",
    }
    assert context.taxonomy is data.taxonomy
    assert context.constraints is data.constraints
    assert context.config is data.config

    with pytest.raises(TypeError):
        context.students_by_id["S3"] = StudentProfile(  # type: ignore[index]
            student_id="S3", name="Student S3"
        )
    with pytest.raises(TypeError):
        context.projects_by_id["P3"] = ProjectProfile(  # type: ignore[index]
            project_id="P3", name="Project P3"
        )
    with pytest.raises(TypeError):
        context.taxonomy_nodes_by_id["other"] = (  # type: ignore[index]
            data.taxonomy.nodes[0]
        )
    with pytest.raises(TypeError):
        context.taxonomy_parent_by_id["other"] = None  # type: ignore[index]
