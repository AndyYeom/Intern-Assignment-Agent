"""Role-aware administrator authorization boundary."""

from typing import Protocol

from project_catalog_agent.admin.roles import AdminRole


class AdminAuthorizer(Protocol):
    """Verify that an authenticated actor holds a required role."""

    def is_authorized(
        self,
        *,
        actor_id: str,
        required_role: AdminRole,
    ) -> bool:
        """Return whether the configured actor holds the required role."""
        ...
