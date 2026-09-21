"""Requirement extraction interface."""

from typing import Protocol

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
)


class RequirementExtractor(Protocol):
    """Convert a project request into structured skill requirements."""

    async def extract(
        self,
        request: CreateProjectRequest,
    ) -> RequirementExtractionResult:
        """Extract structured requirements from a validated request."""
        ...
