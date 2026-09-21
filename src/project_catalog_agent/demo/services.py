"""Controlled service implementations isolated from production business logic."""

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
)


class ControlledRequirementExtractor:
    """Return a detached predefined extraction result."""

    def __init__(self, result: RequirementExtractionResult) -> None:
        self._result = result

    async def extract(
        self, request: CreateProjectRequest
    ) -> RequirementExtractionResult:
        del request
        return self._result.model_copy(deep=True)


class ControlledTaxonomyNormalizer:
    """Return a detached predefined normalization result."""

    def __init__(self, result: TaxonomyNormalizationResult) -> None:
        self._result = result

    async def normalize(
        self, extraction: RequirementExtractionResult
    ) -> TaxonomyNormalizationResult:
        del extraction
        return self._result.model_copy(deep=True)
