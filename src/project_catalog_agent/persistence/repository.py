"""Validated-project repository boundary."""

from typing import Protocol

from project_catalog_agent.persistence.contracts import StoredProject


class ProjectRepository(Protocol):
    """Storage operations required by guarded publication and future handoff."""

    def create(self, project: StoredProject) -> StoredProject:
        """Create one project or raise a known repository exception."""
        ...

    def get_by_request_id(self, request_id: str) -> StoredProject | None:
        """Return the project created for one technical request ID."""
        ...

    def get_by_project_id(self, project_id: str) -> StoredProject | None:
        """Return one project by publication ID."""
        ...

    def list_projects(self) -> tuple[StoredProject, ...]:
        """Return projects in deterministic insertion order."""
        ...
