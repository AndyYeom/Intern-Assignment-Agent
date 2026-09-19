"""Tests for structured LLM taxonomy selection and its prompts."""

import asyncio
from typing import Any

import pytest

from project_catalog_agent.catalog.contracts import (
    ExtractedRequirement,
    ProficiencyLevel,
    RequirementImportance,
    TaxonomySelection,
    TaxonomySkill,
)
from project_catalog_agent.taxonomy import (
    FakeTaxonomyMappingSelector,
    LLMTaxonomyMappingSelector,
    TaxonomySelectionError,
    TaxonomySelectionResponseError,
)
from project_catalog_agent.taxonomy.prompts import (
    TAXONOMY_SELECTION_SYSTEM_PROMPT,
    build_taxonomy_selection_user_prompt,
    format_taxonomy_context,
)


class RecordingClient:
    """Controlled structured client for selector tests."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[Any],
    ) -> Any:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": response_model,
            }
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def requirement(raw_skill: str = "vector search") -> ExtractedRequirement:
    """Build one selector input requirement."""
    return ExtractedRequirement(
        raw_skill=raw_skill,
        importance=RequirementImportance.LEARNING_OPPORTUNITY,
        required_level=ProficiencyLevel.ENTRY,
        confidence=0.8,
        evidence_text="Students will learn vector search.",
        decision_basis="Learning is explicitly stated.",
    )


def skills() -> tuple[TaxonomySkill, ...]:
    """Build deliberately unsorted active and inactive taxonomy entries."""
    return (
        TaxonomySkill(
            skill_id="rag",
            canonical_name="RAG & Vector Search",
            aliases=["embeddings", "faiss"],
            category="AI/ML",
        ),
        TaxonomySkill(
            skill_id="python",
            canonical_name="Python",
            aliases=["py"],
            category="Language",
        ),
        TaxonomySkill(
            skill_id="inactive",
            canonical_name="Inactive",
            category="Other",
            active=False,
        ),
    )


def test_selector_requests_taxonomy_selection_with_complete_context() -> None:
    expected = TaxonomySelection(
        decision="select",
        selected_skill_id="rag",
        decision_basis="Vector search is explicitly grouped by the taxonomy.",
    )
    client = RecordingClient(expected)
    selector = LLMTaxonomyMappingSelector(client)

    result = asyncio.run(
        selector.select(requirement=requirement(), taxonomy_skills=skills())
    )

    assert result == expected
    assert client.calls[0]["response_model"] is TaxonomySelection
    user_prompt = str(client.calls[0]["user_prompt"])
    assert user_prompt.index("python | Python") < user_prompt.index("rag | RAG")
    assert "inactive | Inactive" not in user_prompt
    for field in (
        "raw_skill",
        "importance",
        "required_level",
        "evidence_text",
        "decision_basis",
    ):
        assert field in user_prompt


def test_prompt_states_required_conservative_rules() -> None:
    prompt = TAXONOMY_SELECTION_SYSTEM_PROMPT

    assert "taxonomy.json is the only source" in prompt
    assert "Related does not mean equivalent" in prompt
    assert "performance optimization" in prompt
    assert "LLM response evaluation" in prompt
    assert "Prefer unmapped" in prompt
    assert "Do not modify or reassess" in prompt
    assert "needs_review" in prompt


def test_taxonomy_context_has_stable_format_and_aliases() -> None:
    context = format_taxonomy_context(skills())

    assert context.splitlines() == [
        "python | Python | Language | py",
        "rag | RAG & Vector Search | AI/ML | embeddings, faiss",
    ]
    assert "ACTIVE TAXONOMY" in build_taxonomy_selection_user_prompt(
        requirement(),
        skills(),
    )


@pytest.mark.parametrize("response", [None, {}, {"decision": "select"}])
def test_malformed_or_empty_output_becomes_response_error(response: object) -> None:
    selector = LLMTaxonomyMappingSelector(RecordingClient(response))

    with pytest.raises(TaxonomySelectionResponseError):
        asyncio.run(
            selector.select(requirement=requirement(), taxonomy_skills=skills())
        )


def test_provider_error_becomes_selection_error() -> None:
    selector = LLMTaxonomyMappingSelector(RecordingClient(RuntimeError("offline")))

    with pytest.raises(TaxonomySelectionError):
        asyncio.run(
            selector.select(requirement=requirement(), taxonomy_skills=skills())
        )


def test_fake_selector_records_calls_and_fails_when_unconfigured() -> None:
    fake = FakeTaxonomyMappingSelector({})

    with pytest.raises(TaxonomySelectionError, match="no fake taxonomy selection"):
        asyncio.run(fake.select(requirement=requirement(), taxonomy_skills=skills()))

    assert fake.calls[0][0].raw_skill == "vector search"
