"""SQLite validated-project repository for explicit local persistence."""

import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from project_catalog_agent.persistence.contracts import StoredProject
from project_catalog_agent.persistence.errors import (
    ProjectRepositoryConflictError,
    ProjectRepositoryDataError,
    ProjectRepositoryError,
)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS catalog_projects (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL UNIQUE,
    stored_project_json TEXT NOT NULL
)
"""


class SQLiteProjectRepository:
    """Persist validated projects as revalidated JSON using parameterized SQL."""

    def __init__(self, path: Path) -> None:
        self._path = path
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(_CREATE_TABLE)
        except sqlite3.Error as error:
            raise ProjectRepositoryError(
                "project repository initialization failed"
            ) from error

    def create(self, project: StoredProject) -> StoredProject:
        """Transactionally insert one unique validated record."""
        validated = StoredProject.model_validate(project.model_dump())
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO catalog_projects (
                        project_id, request_id, stored_project_json
                    ) VALUES (?, ?, ?)
                    """,
                    (
                        validated.project_id,
                        validated.request_id,
                        validated.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ProjectRepositoryConflictError(
                "project identity already exists"
            ) from error
        except sqlite3.Error as error:
            raise ProjectRepositoryError("project repository create failed") from error
        return validated.model_copy(deep=True)

    def get_by_request_id(self, request_id: str) -> StoredProject | None:
        """Load and revalidate one record by request ID."""
        return self._fetch_one(
            "SELECT stored_project_json FROM catalog_projects WHERE request_id = ?",
            request_id,
        )

    def get_by_project_id(self, project_id: str) -> StoredProject | None:
        """Load and revalidate one record by project ID."""
        return self._fetch_one(
            "SELECT stored_project_json FROM catalog_projects WHERE project_id = ?",
            project_id,
        )

    def list_projects(self) -> tuple[StoredProject, ...]:
        """Load all records in deterministic insertion order."""
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT stored_project_json
                    FROM catalog_projects
                    ORDER BY sequence ASC
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise ProjectRepositoryError("project repository query failed") from error
        return tuple(self._deserialize(str(row[0])) for row in rows)

    def _fetch_one(self, query: str, identity: str) -> StoredProject | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(query, (identity,)).fetchone()
        except sqlite3.Error as error:
            raise ProjectRepositoryError("project repository query failed") from error
        return self._deserialize(str(row[0])) if row is not None else None

    @staticmethod
    def _deserialize(raw_json: str) -> StoredProject:
        try:
            return StoredProject.model_validate_json(raw_json)
        except (ValidationError, ValueError) as error:
            raise ProjectRepositoryDataError(
                "stored project data failed validation"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)
