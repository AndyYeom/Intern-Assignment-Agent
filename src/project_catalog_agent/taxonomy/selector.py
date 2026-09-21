"""Interfaces and implementations for unresolved taxonomy selection."""

from typing import Protocol

from pydantic import BaseModel, ValidationError

from project_catalog_agent.catalog.contracts import (
    ExtractedRequirement,
    TaxonomySelection,
    TaxonomySkill,
)
from project_catalog_agent.llm import StructuredLLMClient
from project_catalog_agent.taxonomy.errors import (
    TaxonomySelectionError,
    TaxonomySelectionResponseError,
)
from project_catalog_agent.taxonomy.prompts import (
    TAXONOMY_SELECTION_SYSTEM_PROMPT,
    build_taxonomy_selection_user_prompt,
)


class TaxonomyMappingSelector(Protocol):
    """Propose a taxonomy outcome for one unresolved extracted skill."""

    async def select(
        self,
        *,
        requirement: ExtractedRequirement,
        taxonomy_skills: tuple[TaxonomySkill, ...],
    ) -> TaxonomySelection:
        """Return a proposal restricted to the supplied taxonomy."""
        ...


class FakeTaxonomyMappingSelector:
    """Return configured proposals and record detached calls for tests."""

    def __init__(self, results: dict[str, TaxonomySelection]) -> None:
        """Copy configured results so instances never share mutable state."""
        self._results = {
            raw_skill: result.model_copy(deep=True)
            for raw_skill, result in results.items()
        }
        self.calls: list[tuple[ExtractedRequirement, tuple[TaxonomySkill, ...]]] = []

    async def select(
        self,
        *,
        requirement: ExtractedRequirement,
        taxonomy_skills: tuple[TaxonomySkill, ...],
    ) -> TaxonomySelection:
        """Record the call and return its configured detached proposal."""
        copied_requirement = requirement.model_copy(deep=True)
        copied_skills = tuple(skill.model_copy(deep=True) for skill in taxonomy_skills)
        self.calls.append((copied_requirement, copied_skills))
        result = self._results.get(requirement.raw_skill)
        if result is None:
            msg = f"no fake taxonomy selection configured for {requirement.raw_skill!r}"
            raise TaxonomySelectionError(msg)
        return result.model_copy(deep=True)


class LLMTaxonomyMappingSelector:
    """Request a structured, conservative mapping proposal from an LLM."""

    def __init__(self, client: StructuredLLMClient) -> None:
        """Configure the provider-neutral structured client."""
        self._client = client

    async def select(
        self,
        *,
        requirement: ExtractedRequirement,
        taxonomy_skills: tuple[TaxonomySkill, ...],
    ) -> TaxonomySelection:
        """Generate and revalidate a structured taxonomy selection."""
        try:
            generated: object = await self._client.generate_structured(
                system_prompt=TAXONOMY_SELECTION_SYSTEM_PROMPT,
                user_prompt=build_taxonomy_selection_user_prompt(
                    requirement,
                    taxonomy_skills,
                ),
                response_model=TaxonomySelection,
            )
        except TaxonomySelectionResponseError:
            raise
        except Exception as error:
            msg = "taxonomy selection provider request failed"
            raise TaxonomySelectionError(msg) from error

        if generated is None:
            msg = "taxonomy selection provider returned empty output"
            raise TaxonomySelectionResponseError(msg)

        payload = (
            generated.model_dump() if isinstance(generated, BaseModel) else generated
        )
        try:
            return TaxonomySelection.model_validate(payload)
        except ValidationError as error:
            msg = "taxonomy selector returned invalid structured output"
            raise TaxonomySelectionResponseError(msg) from error
