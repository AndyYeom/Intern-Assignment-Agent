"""Project catalog agent: suggest role requirements from a project description.

Runs the existing catalog pipeline (src/project_catalog_agent) on the
project's name and description: LLM requirement extraction -> taxonomy
normalization -> profile build -> validation. Nothing is written: the result
is a suggestion a manager reviews, edits and saves as a role. Capacity is
never suggested; the manager always sets it.
"""

import logging
import os
from typing import Any

from backend.config import RESOURCES

log = logging.getLogger(__name__)

# Used when the model could not settle a level; the manager must confirm it.
DEFAULT_LEVEL = 2
MIN_DESCRIPTION_CHARS = 20


class CatalogUnavailable(RuntimeError):
    """No LLM is configured for the catalog agent."""


class CatalogFailed(RuntimeError):
    """The catalog agent could not produce a suggestion; message is for managers."""


def _client() -> tuple[Any, str]:
    from project_catalog_agent.llm import (
        GatewayStructuredLLMClient,
        OpenAIStructuredLLMClient,
        gateway_configured,
    )

    # OpenAI when a key is configured; otherwise the shared LLM gateway.
    if os.getenv("OPENAI_API_KEY", "").strip():
        from project_catalog_agent.config.settings import Settings

        return OpenAIStructuredLLMClient.from_settings(Settings()), "openai"
    if gateway_configured():
        return GatewayStructuredLLMClient.from_environment(), "gateway"
    raise CatalogUnavailable("No language model is configured for the catalog agent (LLM_* settings).")


async def suggest_requirements(request_id: str, name: str, description: str) -> dict[str, Any]:
    from project_catalog_agent.catalog.contracts import CreateProjectRequest
    from project_catalog_agent.extraction.llm_extractor import LLMRequirementExtractor
    from project_catalog_agent.profile.builder import ProjectProfileBuilder
    from project_catalog_agent.profile.validator import ProjectProfileValidator
    from project_catalog_agent.taxonomy.json_repository import JsonTaxonomyRepository
    from project_catalog_agent.taxonomy.normalizer import HybridTaxonomyNormalizer
    from project_catalog_agent.taxonomy.selector import LLMTaxonomyMappingSelector

    if len(description.strip()) < MIN_DESCRIPTION_CHARS:
        raise CatalogFailed(
            "Add a project description (a few sentences about the work and stack) first; "
            "the catalog agent reads the description."
        )
    client, provider = _client()
    request = CreateProjectRequest(
        request_id=request_id, project_name=name, project_description=description
    )
    taxonomy = JsonTaxonomyRepository(RESOURCES / "taxonomy.json")
    try:
        extraction = await LLMRequirementExtractor(client).extract(request)
        normalization = await HybridTaxonomyNormalizer(
            taxonomy, LLMTaxonomyMappingSelector(client)
        ).normalize(extraction)
        profile = ProjectProfileBuilder().build(
            request=request, extraction=extraction, normalization=normalization
        )
        validation = ProjectProfileValidator(taxonomy_repository=taxonomy).validate(profile)
    except Exception as exc:
        log.warning("catalog agent failed request=%s: %s", request_id, exc)
        raise CatalogFailed(
            f"The catalog agent could not analyse this description ({type(exc).__name__}). Try again."
        ) from exc

    return {
        "provider": provider,
        "summary": profile.project_summary,
        "requirements": [
            {
                "skill_id": r.skill_id,
                "skill_name": r.canonical_name,
                "requirement_type": r.importance.value,
                "required_level": int(r.required_level) if r.required_level else DEFAULT_LEVEL,
                "level_suggested": r.required_level is not None,
                "weight": 1.0,
                "confidence": r.confidence,
                "evidence_text": r.evidence_text,
                "decision_basis": r.decision_basis,
            }
            for r in profile.requirements
        ],
        "unresolved": [
            {
                "raw_skill": u.raw_skill,
                "requirement_type": u.importance.value,
                "candidate_skill_ids": list(u.candidate_skill_ids),
            }
            for u in profile.unresolved_requirements
        ],
        "uncertainties": list(extraction.uncertainties),
        "issues": [i.message for i in validation.issues],
    }
