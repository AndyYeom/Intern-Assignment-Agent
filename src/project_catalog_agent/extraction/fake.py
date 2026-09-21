"""Deterministic requirement extractor for tests and local integration."""

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
)


class FakeRequirementExtractor:
    """Return a predefined extraction result and record received requests."""

    def __init__(self, result: RequirementExtractionResult) -> None:
        """Store a detached copy of the configured result."""
        self._result = result.model_copy(deep=True)
        self.received_requests: list[CreateProjectRequest] = []

    async def extract(
        self,
        request: CreateProjectRequest,
    ) -> RequirementExtractionResult:
        """Record the request and return a detached result copy."""
        validated_request = CreateProjectRequest.model_validate(request.model_dump())
        self.received_requests.append(validated_request.model_copy(deep=True))
        return self._result.model_copy(deep=True)
