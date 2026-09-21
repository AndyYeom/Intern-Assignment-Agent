"""JSON loading and lookup construction for matching inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pydantic import ValidationError

from .schemas import (
    GAConfig,
    MatchingConstraints,
    MatchingInput,
    ProjectProfile,
    StudentProfile,
    TaxonomyNode,
    TaxonomyTree,
)


def _normalize_student_record(record: object) -> object:
    if not isinstance(record, dict):
        return record
    normalized = dict(record)
    normalized.setdefault("name", normalized.get("student_id", ""))
    skills = normalized.get("skills")
    if isinstance(skills, list):
        normalized["skills"] = [
            {
                **skill,
                "skill_id": skill["skill"],
            }
            if isinstance(skill, dict)
            and "skill_id" not in skill
            and "skill" in skill
            else skill
            for skill in skills
        ]
    return normalized


def _normalize_project_record(record: object) -> object:
    if not isinstance(record, dict):
        return record
    normalized = dict(record)
    normalized.setdefault("name", normalized.get("project_id", ""))
    team_size = normalized.get("team_size")
    if isinstance(team_size, dict):
        normalized.setdefault("min_team_size", team_size.get("min"))
        normalized.setdefault("max_team_size", team_size.get("max"))

    requirements = normalized.get("requirements")
    if isinstance(requirements, list):
        normalized_requirements: list[object] = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                normalized_requirements.append(requirement)
                continue
            normalized_requirement = dict(requirement)
            if "skill_id" not in normalized_requirement and "skill" in requirement:
                normalized_requirement["skill_id"] = requirement["skill"]
            if (
                "required_level" not in normalized_requirement
                and "level" in requirement
            ):
                normalized_requirement["required_level"] = requirement["level"]
            legacy_importance = normalized_requirement.get("importance")
            if "requirement_type" not in normalized_requirement:
                requirement_types = {
                    "hard": "hard_requirement",
                    "soft": "preferred",
                    "learning": "learning_opportunity",
                }
                normalized_requirement["requirement_type"] = requirement_types.get(
                    legacy_importance, "preferred"
                )
            if not isinstance(legacy_importance, (int, float)):
                normalized_requirement["importance"] = 1.0
            normalized_requirements.append(normalized_requirement)
        normalized["requirements"] = normalized_requirements
    return normalized


def _normalize_taxonomy_data(data: object) -> object:
    if not isinstance(data, dict) or "nodes" in data or "skills" not in data:
        return data
    skills = data["skills"]
    if not isinstance(skills, list):
        return data

    root_id = "__taxonomy_root__"
    nodes: list[dict[str, object]] = [
        {"skill_id": root_id, "name": "Skills", "parent_id": None}
    ]
    category_ids: dict[str, str] = {}
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        category = str(skill.get("category", "Uncategorized"))
        if category not in category_ids:
            category_id = f"__category__:{category.casefold()}"
            category_ids[category] = category_id
            nodes.append(
                {
                    "skill_id": category_id,
                    "name": category,
                    "parent_id": root_id,
                }
            )
        nodes.append(
            {
                "skill_id": skill.get("id"),
                "name": skill.get("name"),
                "parent_id": category_ids[category],
            }
        )
    return {"nodes": nodes}


def _read_json(path: str | Path) -> object:
    json_path = Path(path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON file does not exist: {json_path}")
    if not json_path.is_file():
        raise IsADirectoryError(f"JSON path is not a file: {json_path}")

    try:
        content = json_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Could not read JSON file {json_path}: {exc}") from exc

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {json_path}: {exc}") from exc


def _extract_records(data: object, wrapper_key: str, path: Path) -> list[object]:
    records: object
    if isinstance(data, dict):
        if wrapper_key not in data:
            return [data]
        records = data[wrapper_key]
        if not isinstance(records, list):
            raise ValueError(f"'{wrapper_key}' in {path} must be a list")
    elif isinstance(data, list):
        records = data
    else:
        raise ValueError(f"JSON root in {path} must be an object or list")

    if not records:
        raise ValueError(f"Record list in {path} must not be empty")
    return records


def load_student_files(paths: Sequence[str | Path]) -> list[StudentProfile]:
    if not paths:
        raise ValueError("At least one student file is required")

    students: list[StudentProfile] = []
    first_path_by_id: dict[str, Path] = {}
    for path in paths:
        source_path = Path(path)
        records = _extract_records(_read_json(source_path), "students", source_path)
        for index, record in enumerate(records):
            try:
                student = StudentProfile.model_validate(
                    _normalize_student_record(record)
                )
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid student record in {source_path} at index {index}: {exc}"
                ) from exc

            first_path = first_path_by_id.get(student.student_id)
            if first_path is not None:
                raise ValueError(
                    f"Duplicate student ID '{student.student_id}' in {source_path}; "
                    f"first found in {first_path}"
                )
            first_path_by_id[student.student_id] = source_path
            students.append(student)
    return students


def load_project_files(paths: Sequence[str | Path]) -> list[ProjectProfile]:
    if not paths:
        raise ValueError("At least one project file is required")

    projects: list[ProjectProfile] = []
    first_path_by_id: dict[str, Path] = {}
    for path in paths:
        source_path = Path(path)
        records = _extract_records(_read_json(source_path), "projects", source_path)
        for index, record in enumerate(records):
            try:
                project = ProjectProfile.model_validate(
                    _normalize_project_record(record)
                )
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid project record in {source_path} at index {index}: {exc}"
                ) from exc

            first_path = first_path_by_id.get(project.project_id)
            if first_path is not None:
                raise ValueError(
                    f"Duplicate project ID '{project.project_id}' in {source_path}; "
                    f"first found in {first_path}"
                )
            first_path_by_id[project.project_id] = source_path
            projects.append(project)
    return projects


def load_taxonomy_file(path: str | Path) -> TaxonomyTree:
    source_path = Path(path)
    data = _normalize_taxonomy_data(_read_json(source_path))
    if isinstance(data, list):
        value: object = {"nodes": data}
    elif isinstance(data, dict) and "nodes" in data:
        value = data
    else:
        raise ValueError(
            f"Taxonomy JSON in {source_path} must be a node list or an object "
            "containing 'nodes'"
        )

    try:
        return TaxonomyTree.model_validate(value)
    except ValidationError as exc:
        raise ValueError(f"Invalid taxonomy in {source_path}: {exc}") from exc


def load_constraints_file(path: str | Path | None) -> MatchingConstraints:
    if path is None:
        return MatchingConstraints()

    source_path = Path(path)
    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError(f"Constraints JSON in {source_path} must be an object")
    try:
        return MatchingConstraints.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid constraints in {source_path}: {exc}") from exc


def load_config_file(path: str | Path | None) -> GAConfig:
    if path is None:
        return GAConfig()

    source_path = Path(path)
    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError(f"GA configuration JSON in {source_path} must be an object")
    try:
        return GAConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid GA configuration in {source_path}: {exc}") from exc


def load_matching_input(
    student_paths: Sequence[str | Path],
    project_paths: Sequence[str | Path],
    taxonomy_path: str | Path,
    constraints_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> MatchingInput:
    return MatchingInput(
        students=load_student_files(student_paths),
        projects=load_project_files(project_paths),
        taxonomy=load_taxonomy_file(taxonomy_path),
        constraints=load_constraints_file(constraints_path),
        config=load_config_file(config_path),
    )


@dataclass(frozen=True)
class MatchingContext:
    students: tuple[StudentProfile, ...]
    projects: tuple[ProjectProfile, ...]
    students_by_id: Mapping[str, StudentProfile]
    projects_by_id: Mapping[str, ProjectProfile]
    taxonomy: TaxonomyTree
    taxonomy_nodes_by_id: Mapping[str, TaxonomyNode]
    taxonomy_parent_by_id: Mapping[str, str | None]
    constraints: MatchingConstraints
    config: GAConfig


def preprocess_inputs(data: MatchingInput) -> MatchingContext:
    students = tuple(data.students)
    projects = tuple(data.projects)
    students_by_id = {student.student_id: student for student in students}
    projects_by_id = {project.project_id: project for project in projects}
    taxonomy_nodes_by_id = {
        node.skill_id: node for node in data.taxonomy.nodes
    }
    taxonomy_parent_by_id = {
        node.skill_id: node.parent_id for node in data.taxonomy.nodes
    }

    return MatchingContext(
        students=students,
        projects=projects,
        students_by_id=MappingProxyType(students_by_id),
        projects_by_id=MappingProxyType(projects_by_id),
        taxonomy=data.taxonomy,
        taxonomy_nodes_by_id=MappingProxyType(taxonomy_nodes_by_id),
        taxonomy_parent_by_id=MappingProxyType(taxonomy_parent_by_id),
        constraints=data.constraints,
        config=data.config,
    )
