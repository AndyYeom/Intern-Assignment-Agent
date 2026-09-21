"""Tests for in-memory and SQLite validated-project repositories."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from project_catalog_agent.persistence import (
    InMemoryProjectRepository,
    ProjectRepositoryConflictError,
    ProjectRepositoryDataError,
    SQLiteProjectRepository,
)
from tests.persistence.helpers import stored_project


def test_in_memory_create_lookup_and_order_are_detached() -> None:
    repository = InMemoryProjectRepository()
    first = stored_project("PRJ-001")
    second = stored_project("PRJ-002").model_copy(
        update={"request_id": "STATE-002"}, deep=True
    )
    second = second.model_copy(
        update={
            "project_profile": second.project_profile.model_copy(
                update={"request_id": "STATE-002"}, deep=True
            )
        },
        deep=True,
    )
    second = type(second).model_validate(second.model_dump())

    created = repository.create(first)
    repository.create(second)
    created.project_profile.requirements.clear()

    assert repository.get_by_request_id("STATE-001") == first
    assert repository.get_by_project_id("PRJ-001") == first
    assert [item.project_id for item in repository.list_projects()] == [
        "PRJ-001",
        "PRJ-002",
    ]
    assert repository.get_by_project_id("missing") is None


def test_in_memory_rejects_duplicate_request_and_project_ids() -> None:
    repository = InMemoryProjectRepository()
    project = stored_project()
    repository.create(project)

    with pytest.raises(ProjectRepositoryConflictError):
        repository.create(project.model_copy(update={"project_id": "PRJ-OTHER"}))

    different_request = project.model_copy(
        update={
            "request_id": "OTHER",
            "project_profile": project.project_profile.model_copy(
                update={"request_id": "OTHER"}, deep=True
            ),
        },
        deep=True,
    )
    with pytest.raises(ProjectRepositoryConflictError):
        repository.create(different_request)


def test_sqlite_schema_round_trip_order_and_uniqueness(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    repository = SQLiteProjectRepository(path)
    project = stored_project()

    created = repository.create(project)

    assert path.exists()
    assert created == project
    assert repository.get_by_request_id(project.request_id) == project
    assert repository.get_by_project_id(project.project_id) == project
    assert repository.list_projects() == (project,)
    assert repository.get_by_request_id("' OR 1=1 --") is None
    with pytest.raises(ProjectRepositoryConflictError):
        repository.create(project.model_copy(update={"project_id": "PRJ-OTHER"}))

    different_request = project.model_copy(
        update={
            "request_id": "OTHER",
            "project_profile": project.project_profile.model_copy(
                update={"request_id": "OTHER"}, deep=True
            ),
        },
        deep=True,
    )
    with pytest.raises(ProjectRepositoryConflictError):
        repository.create(different_request)


def test_sqlite_rejects_invalid_stored_json_safely(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.sqlite3"
    repository = SQLiteProjectRepository(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO catalog_projects (
                project_id, request_id, stored_project_json
            ) VALUES (?, ?, ?)
            """,
            ("PRJ-BAD", "REQ-BAD", "{not-json"),
        )

    with pytest.raises(ProjectRepositoryDataError):
        repository.get_by_request_id("REQ-BAD")


def test_sqlite_initialization_failure_is_translated(tmp_path: Path) -> None:
    directory = tmp_path / "not-a-database"
    directory.mkdir()

    from project_catalog_agent.persistence import ProjectRepositoryError

    with pytest.raises(ProjectRepositoryError):
        SQLiteProjectRepository(directory)
