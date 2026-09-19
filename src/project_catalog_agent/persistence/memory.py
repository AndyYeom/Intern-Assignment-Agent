"""In-memory validated-project repository for tests and demonstrations."""

from project_catalog_agent.persistence.contracts import StoredProject
from project_catalog_agent.persistence.errors import ProjectRepositoryConflictError


class InMemoryProjectRepository:
    """Preserve detached projects in deterministic insertion order."""

    def __init__(self) -> None:
        self._by_project_id: dict[str, StoredProject] = {}
        self._project_id_by_request_id: dict[str, str] = {}

    def create(self, project: StoredProject) -> StoredProject:
        """Create a unique detached project record."""
        validated = StoredProject.model_validate(project.model_dump())
        if validated.request_id in self._project_id_by_request_id:
            raise ProjectRepositoryConflictError("request ID already exists")
        if validated.project_id in self._by_project_id:
            raise ProjectRepositoryConflictError("project ID already exists")
        stored = validated.model_copy(deep=True)
        self._by_project_id[stored.project_id] = stored
        self._project_id_by_request_id[stored.request_id] = stored.project_id
        return stored.model_copy(deep=True)

    def get_by_request_id(self, request_id: str) -> StoredProject | None:
        """Return a detached record for a technical request ID."""
        project_id = self._project_id_by_request_id.get(request_id)
        return self.get_by_project_id(project_id) if project_id is not None else None

    def get_by_project_id(self, project_id: str) -> StoredProject | None:
        """Return a detached record for a publication ID."""
        project = self._by_project_id.get(project_id)
        return project.model_copy(deep=True) if project is not None else None

    def list_projects(self) -> tuple[StoredProject, ...]:
        """Return detached records in insertion order."""
        return tuple(
            item.model_copy(deep=True) for item in self._by_project_id.values()
        )
