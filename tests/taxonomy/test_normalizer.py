"""Tests for hybrid taxonomy normalization."""

import asyncio

import pytest

from project_catalog_agent.catalog.contracts import (
    ExtractedRequirement,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyNormalizationResult,
    TaxonomySelection,
)
from project_catalog_agent.taxonomy import (
    FakeTaxonomyMappingSelector,
    HybridTaxonomyNormalizer,
    JsonTaxonomyRepository,
    TaxonomyNormalizationError,
    TaxonomySelectionResponseError,
)


def requirement(
    raw_skill: str,
    *,
    importance: RequirementImportance = RequirementImportance.HARD_REQUIREMENT,
    level: ProficiencyLevel = ProficiencyLevel.INTERMEDIATE,
) -> ExtractedRequirement:
    """Build an extracted requirement with recognizable provenance."""
    return ExtractedRequirement(
        raw_skill=raw_skill,
        importance=importance,
        required_level=level,
        confidence=0.73,
        evidence_text=f"Verbatim evidence for {raw_skill}",
        decision_basis=f"Extraction basis for {raw_skill}",
    )


def extraction(*raw_skills: str) -> RequirementExtractionResult:
    """Build a result with requirements in the given order."""
    return RequirementExtractionResult(
        project_summary="Normalization test",
        requirements=[requirement(raw_skill) for raw_skill in raw_skills],
    )


def normalize(
    value: RequirementExtractionResult,
    selector: FakeTaxonomyMappingSelector | None = None,
) -> TaxonomyNormalizationResult:
    """Run normalization against the packaged repository."""
    normalizer = HybridTaxonomyNormalizer(JsonTaxonomyRepository(), selector)
    return asyncio.run(normalizer.normalize(value))


@pytest.mark.parametrize(
    ("raw_skill", "skill_id", "method"),
    [
        ("Python", "python", MatchMethod.EXACT),
        ("PYTHON", "python", MatchMethod.EXACT),
        ("py", "python", MatchMethod.ALIAS),
        ("FastAPI", "flask-fastapi", MatchMethod.ALIAS),
        ("retrieval-augmented generation", "rag", MatchMethod.ALIAS),
        ("embeddings", "rag", MatchMethod.ALIAS),
        ("ML", "machine-learning", MatchMethod.ALIAS),
        ("reactjs", "react", MatchMethod.ALIAS),
    ],
)
def test_deterministic_mapping(
    raw_skill: str,
    skill_id: str,
    method: MatchMethod,
) -> None:
    selector = FakeTaxonomyMappingSelector({})

    result = normalize(extraction(raw_skill), selector)
    mapping = result.mappings[0]

    assert mapping.status is MappingStatus.RESOLVED
    assert mapping.skill_id == skill_id
    assert mapping.match_method is method
    assert mapping.match_score is None
    assert selector.calls == []


def test_unknown_value_does_not_falsely_resolve_without_selector() -> None:
    result = normalize(extraction("Performance Optimization"))

    mapping = result.mappings[0]
    assert mapping.status is MappingStatus.UNMAPPED
    assert mapping.match_method is MatchMethod.UNRESOLVED


@pytest.mark.parametrize(
    ("raw_skill", "selected_id", "canonical_name"),
    [
        ("vector search", "rag", "RAG & Vector Search"),
        ("machine-learning", "machine-learning", "Machine Learning"),
    ],
)
def test_llm_selected_mapping_uses_repository_canonical_name(
    raw_skill: str,
    selected_id: str,
    canonical_name: str,
) -> None:
    selector = FakeTaxonomyMappingSelector(
        {
            raw_skill: TaxonomySelection(
                decision="select",
                selected_skill_id=selected_id,
                decision_basis="Substantially equivalent capability.",
                match_score=0.8,
            )
        }
    )

    result = normalize(extraction(raw_skill), selector)
    mapping = result.mappings[0]

    assert mapping.status is MappingStatus.RESOLVED
    assert mapping.match_method is MatchMethod.LLM_SELECTED
    assert mapping.canonical_skill == canonical_name
    assert len(selector.calls) == 1
    assert len(selector.calls[0][1]) == len(JsonTaxonomyRepository().list_skills())


@pytest.mark.parametrize("field", ["selected", "candidate"])
def test_invented_taxonomy_id_is_rejected(field: str) -> None:
    selection = (
        TaxonomySelection(
            decision="select",
            selected_skill_id="invented",
            decision_basis="Invalid proposal.",
        )
        if field == "selected"
        else TaxonomySelection(
            decision="needs_review",
            candidate_skill_ids=["python", "invented"],
            decision_basis="Invalid candidates.",
        )
    )
    selector = FakeTaxonomyMappingSelector({"unknown": selection})

    with pytest.raises(TaxonomySelectionResponseError):
        normalize(extraction("unknown"), selector)


class FailingSelector:
    """Selector that simulates an unexpected provider failure."""

    async def select(self, **_: object) -> TaxonomySelection:
        """Raise an untyped provider exception."""
        raise RuntimeError("provider unavailable")


def test_selector_provider_failure_becomes_normalization_error() -> None:
    normalizer = HybridTaxonomyNormalizer(
        JsonTaxonomyRepository(),
        FailingSelector(),
    )

    with pytest.raises(TaxonomyNormalizationError):
        asyncio.run(normalizer.normalize(extraction("unknown")))


@pytest.mark.parametrize(
    "raw_skill",
    ["Performance Optimization", "evaluation of LLM responses"],
)
def test_selector_can_return_meaningful_unmapped_skill(raw_skill: str) -> None:
    selector = FakeTaxonomyMappingSelector(
        {
            raw_skill: TaxonomySelection(
                decision="unmapped",
                decision_basis="No supplied taxonomy skill is equivalent.",
            )
        }
    )

    result = normalize(extraction(raw_skill), selector)
    mapping = result.mappings[0]

    assert mapping.status is MappingStatus.UNMAPPED
    assert mapping.skill_id is None
    assert result.unresolved_skills == [raw_skill]


def test_compound_skill_needs_review_without_selector() -> None:
    result = normalize(extraction("PostgreSQL database schema design"))
    mapping = result.mappings[0]

    assert mapping.status is MappingStatus.NEEDS_REVIEW
    assert [candidate.skill_id for candidate in mapping.candidates] == [
        "postgresql",
        "data-modeling",
    ]


def test_review_candidates_are_deduplicated_in_order() -> None:
    selector = FakeTaxonomyMappingSelector(
        {
            "compound": TaxonomySelection(
                decision="needs_review",
                candidate_skill_ids=["postgresql", "postgresql", "data-modeling"],
                decision_basis="Both interpretations are plausible.",
            )
        }
    )

    result = normalize(extraction("compound"), selector)

    assert [candidate.skill_id for candidate in result.mappings[0].candidates] == [
        "postgresql",
        "data-modeling",
    ]


def test_preserves_order_indexes_and_extraction_provenance_without_mutation() -> None:
    source = RequirementExtractionResult(
        project_summary="Preservation test",
        requirements=[
            requirement(
                "retrieval-augmented generation",
                importance=RequirementImportance.LEARNING_OPPORTUNITY,
                level=ProficiencyLevel.ENTRY,
            ),
            requirement("embeddings", level=ProficiencyLevel.ADVANCED),
            requirement("vector search"),
        ],
    )
    before = source.model_dump()
    selector = FakeTaxonomyMappingSelector(
        {
            "vector search": TaxonomySelection(
                decision="select",
                selected_skill_id="rag",
                decision_basis="The taxonomy explicitly groups vector search.",
            )
        }
    )

    result = normalize(source, selector)

    assert [mapping.source_requirement_index for mapping in result.mappings] == [
        0,
        1,
        2,
    ]
    assert [mapping.raw_skill for mapping in result.mappings] == [
        "retrieval-augmented generation",
        "embeddings",
        "vector search",
    ]
    assert [mapping.skill_id for mapping in result.mappings] == ["rag", "rag", "rag"]
    assert source.model_dump() == before
    assert (
        source.requirements[0].importance is RequirementImportance.LEARNING_OPPORTUNITY
    )
    assert source.requirements[0].required_level is ProficiencyLevel.ENTRY
    assert source.requirements[0].evidence_text.startswith("Verbatim")
    assert source.requirements[0].decision_basis.startswith("Extraction")


def test_empty_extraction_produces_no_mappings_or_selector_calls() -> None:
    selector = FakeTaxonomyMappingSelector({})
    source = RequirementExtractionResult(
        project_summary="Nothing to normalize",
        requirements=[],
    )

    result = normalize(source, selector)

    assert result.mappings == []
    assert result.unresolved_skills == []
    assert selector.calls == []
