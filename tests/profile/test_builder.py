"""Tests for deterministic candidate profile construction."""

from collections.abc import Sequence

import pytest

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyCandidate,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.errors import ProjectProfileBuildError
from project_catalog_agent.profile import ProjectProfileBuilder, build_project_profile


def request() -> CreateProjectRequest:
    """Build a controlled external request."""
    return CreateProjectRequest(
        request_id="req-profile-001",
        project_name="Profile Builder",
        project_description="Build a typed project profile.",
    )


def requirement(
    raw_skill: str,
    *,
    importance: RequirementImportance = RequirementImportance.HARD_REQUIREMENT,
    level: ProficiencyLevel | None = ProficiencyLevel.INTERMEDIATE,
    confidence: float = 0.8,
    evidence: str | None = None,
) -> ExtractedRequirement:
    """Build a controlled extraction requirement."""
    return ExtractedRequirement(
        raw_skill=raw_skill,
        importance=importance,
        required_level=level,
        evidence_text=evidence or f"Evidence for {raw_skill}.",
        confidence=confidence,
        decision_basis=f"Extraction basis for {raw_skill}.",
    )


def extraction(
    requirements: Sequence[ExtractedRequirement],
) -> RequirementExtractionResult:
    """Build a controlled extraction result."""
    return RequirementExtractionResult(
        project_summary="A deterministic profile builder test.",
        requirements=list(requirements),
    )


def resolved_mapping(
    index: int,
    raw_skill: str,
    skill_id: str,
    canonical_skill: str,
    *,
    method: MatchMethod = MatchMethod.EXACT,
) -> TaxonomyMapping:
    """Build a resolved taxonomy mapping."""
    return TaxonomyMapping(
        source_requirement_index=index,
        raw_skill=raw_skill,
        status=MappingStatus.RESOLVED,
        match_method=method,
        skill_id=skill_id,
        canonical_skill=canonical_skill,
        match_score=0.55 if method is MatchMethod.LLM_SELECTED else None,
        decision_basis=f"Taxonomy basis for {raw_skill}.",
    )


def unresolved_mapping(
    index: int,
    raw_skill: str,
    *,
    status: MappingStatus = MappingStatus.UNMAPPED,
    candidate_ids: Sequence[str] = (),
) -> TaxonomyMapping:
    """Build an unresolved taxonomy mapping."""
    return TaxonomyMapping(
        source_requirement_index=index,
        raw_skill=raw_skill,
        status=status,
        match_method=MatchMethod.UNRESOLVED,
        candidates=[
            TaxonomyCandidate(skill_id=value, canonical_name=value.title())
            for value in candidate_ids
        ],
        decision_basis=f"No accepted taxonomy identity for {raw_skill}.",
    )


def build(
    requirements: Sequence[ExtractedRequirement],
    mappings: Sequence[TaxonomyMapping],
):  # type: ignore[no-untyped-def]
    """Build a profile using concise controlled inputs."""
    return ProjectProfileBuilder().build(
        request=request(),
        extraction=extraction(requirements),
        normalization=TaxonomyNormalizationResult(mappings=list(mappings)),
    )


def test_basic_resolved_requirement_preserves_fields_and_provenance() -> None:
    source = requirement(
        "Python",
        importance=RequirementImportance.PREFERRED,
        level=None,
        confidence=0.73,
        evidence="Python experience is helpful.",
    )

    profile = build(
        [source],
        [resolved_mapping(0, "Python", "python", "Python")],
    )
    built = profile.requirements[0]

    assert profile.request_id == "req-profile-001"
    assert profile.project_name == "Profile Builder"
    assert profile.project_description == "Build a typed project profile."
    assert profile.project_summary == "A deterministic profile builder test."
    assert built.skill_id == "python"
    assert built.canonical_name == "Python"
    assert built.importance is RequirementImportance.PREFERRED
    assert built.required_level is None
    assert built.evidence_text == "Python experience is helpful."
    assert built.decision_basis == "Extraction basis for Python."
    assert built.confidence == 0.73
    assert built.provenance[0].source_requirement_index == 0
    assert built.provenance[0].extraction_confidence == 0.73
    assert built.provenance[0].taxonomy_decision_basis.startswith("Taxonomy")


def test_mapping_score_is_not_used_as_extraction_confidence() -> None:
    source = requirement("vector search", confidence=0.91)
    mapping = resolved_mapping(
        0,
        "vector search",
        "rag",
        "RAG & Vector Search",
        method=MatchMethod.LLM_SELECTED,
    )

    profile = build([source], [mapping])

    assert mapping.match_score == 0.55
    assert profile.requirements[0].confidence == 0.91


def test_duplicate_canonical_skills_merge_with_precedence_and_provenance() -> None:
    requirements = [
        requirement(
            "retrieval-augmented generation",
            importance=RequirementImportance.LEARNING_OPPORTUNITY,
            level=ProficiencyLevel.ENTRY,
            confidence=0.7,
            evidence="Students will learn RAG.",
        ),
        requirement(
            "embeddings",
            importance=RequirementImportance.PREFERRED,
            level=ProficiencyLevel.INTERMEDIATE,
            confidence=0.8,
        ),
        requirement(
            "vector search",
            importance=RequirementImportance.HARD_REQUIREMENT,
            level=ProficiencyLevel.ADVANCED,
            confidence=0.93,
            evidence="Vector search is required.",
        ),
        requirement(
            "FAISS",
            importance=RequirementImportance.PREFERRED,
            level=None,
            confidence=0.99,
        ),
    ]
    mappings = [
        resolved_mapping(index, source.raw_skill, "rag", "RAG & Vector Search")
        for index, source in enumerate(requirements)
    ]

    profile = build(requirements, mappings)
    merged = profile.requirements[0]

    assert len(profile.requirements) == 1
    assert merged.importance is RequirementImportance.HARD_REQUIREMENT
    assert merged.required_level is ProficiencyLevel.ADVANCED
    assert merged.confidence == 0.93
    assert merged.evidence_text == "Vector search is required."
    assert merged.decision_basis == (
        "Merged from 4 extracted requirements mapped to canonical skill 'rag'."
    )
    assert [item.raw_skill for item in merged.provenance] == [
        "retrieval-augmented generation",
        "embeddings",
        "vector search",
        "FAISS",
    ]
    assert [item.required_level for item in merged.provenance] == [
        ProficiencyLevel.ENTRY,
        ProficiencyLevel.INTERMEDIATE,
        ProficiencyLevel.ADVANCED,
        None,
    ]


def test_preferred_overrides_learning_and_highest_equal_confidence_wins() -> None:
    requirements = [
        requirement(
            "first",
            importance=RequirementImportance.LEARNING_OPPORTUNITY,
            confidence=0.99,
        ),
        requirement(
            "second",
            importance=RequirementImportance.PREFERRED,
            confidence=0.7,
        ),
        requirement(
            "third",
            importance=RequirementImportance.PREFERRED,
            confidence=0.9,
        ),
    ]
    mappings = [
        resolved_mapping(index, source.raw_skill, "rag", "RAG & Vector Search")
        for index, source in enumerate(requirements)
    ]

    merged = build(requirements, mappings).requirements[0]

    assert merged.importance is RequirementImportance.PREFERRED
    assert merged.confidence == 0.9
    assert merged.evidence_text == "Evidence for third."


def test_all_null_levels_remain_null() -> None:
    requirements = [requirement("first", level=None), requirement("second", level=None)]
    mappings = [
        resolved_mapping(index, source.raw_skill, "python", "Python")
        for index, source in enumerate(requirements)
    ]

    merged = build(requirements, mappings).requirements[0]

    assert merged.required_level is None


def test_merged_requirement_order_follows_first_source_index() -> None:
    requirements = [
        requirement("rag first"),
        requirement("Python"),
        requirement("rag second"),
    ]
    mappings = [
        resolved_mapping(2, "rag second", "rag", "RAG & Vector Search"),
        resolved_mapping(1, "Python", "python", "Python"),
        resolved_mapping(0, "rag first", "rag", "RAG & Vector Search"),
    ]

    profile = build(requirements, mappings)

    assert [item.skill_id for item in profile.requirements] == ["rag", "python"]


def test_unresolved_requirements_are_structured_and_skills_are_deduplicated() -> None:
    requirements = [
        requirement("Performance Optimization"),
        requirement("PostgreSQL schema"),
        requirement("Performance Optimization"),
    ]
    mappings = [
        unresolved_mapping(2, "Performance Optimization"),
        unresolved_mapping(0, "Performance Optimization"),
        unresolved_mapping(
            1,
            "PostgreSQL schema",
            status=MappingStatus.NEEDS_REVIEW,
            candidate_ids=["postgresql", "data-modeling"],
        ),
    ]

    profile = build(requirements, mappings)

    assert profile.requirements == []
    assert profile.unresolved_skills == [
        "Performance Optimization",
        "PostgreSQL schema",
    ]
    assert [
        item.source_requirement_index for item in profile.unresolved_requirements
    ] == [
        0,
        1,
        2,
    ]
    assert (
        profile.unresolved_requirements[1].mapping_status is MappingStatus.NEEDS_REVIEW
    )
    assert profile.unresolved_requirements[1].candidate_skill_ids == [
        "postgresql",
        "data-modeling",
    ]


def test_resolved_and_unresolved_sources_are_not_duplicated() -> None:
    requirements = [requirement("Python"), requirement("Unknown")]
    mappings = [
        resolved_mapping(0, "Python", "python", "Python"),
        unresolved_mapping(1, "Unknown"),
    ]

    profile = build(requirements, mappings)

    assert [
        item.provenance[0].source_requirement_index for item in profile.requirements
    ] == [0]
    assert [
        item.source_requirement_index for item in profile.unresolved_requirements
    ] == [1]


@pytest.mark.parametrize(
    ("requirements", "mappings", "message"),
    [
        ([requirement("Python")], [], "Missing normalization mapping"),
        (
            [requirement("Python")],
            [
                resolved_mapping(0, "Python", "python", "Python"),
                resolved_mapping(0, "Python", "python", "Python"),
            ],
            "duplicate normalization mapping",
        ),
        (
            [requirement("Python")],
            [resolved_mapping(1, "Python", "python", "Python")],
            "out of range",
        ),
        (
            [requirement("Python")],
            [resolved_mapping(0, "Py", "python", "Python")],
            "raw skill mismatch",
        ),
        (
            [],
            [unresolved_mapping(0, "Unknown")],
            "out of range",
        ),
    ],
)
def test_input_consistency_errors_raise_build_error(
    requirements: list[ExtractedRequirement],
    mappings: list[TaxonomyMapping],
    message: str,
) -> None:
    with pytest.raises(ProjectProfileBuildError, match=message):
        build(requirements, mappings)


def test_inconsistent_canonical_names_for_same_id_raise() -> None:
    requirements = [requirement("first"), requirement("second")]
    mappings = [
        resolved_mapping(0, "first", "rag", "RAG & Vector Search"),
        resolved_mapping(1, "second", "rag", "Different Name"),
    ]

    with pytest.raises(ProjectProfileBuildError, match="canonical name mismatch"):
        build(requirements, mappings)


@pytest.mark.parametrize("status", [MappingStatus.RESOLVED, MappingStatus.UNMAPPED])
def test_builder_rejects_structurally_invalid_constructed_mapping(
    status: MappingStatus,
) -> None:
    source = requirement("Python")
    if status is MappingStatus.RESOLVED:
        invalid = TaxonomyMapping.model_construct(
            source_requirement_index=0,
            raw_skill="Python",
            status=status,
            match_method=MatchMethod.EXACT,
            skill_id=None,
            canonical_skill=None,
            candidates=[],
            match_score=None,
            decision_basis="Invalid resolved mapping.",
        )
        message = "resolved mapping"
    else:
        invalid = TaxonomyMapping.model_construct(
            source_requirement_index=0,
            raw_skill="Python",
            status=status,
            match_method=MatchMethod.UNRESOLVED,
            skill_id="python",
            canonical_skill="Python",
            candidates=[],
            match_score=None,
            decision_basis="Invalid unresolved mapping.",
        )
        message = "unresolved mapping"
    normalization = TaxonomyNormalizationResult.model_construct(
        mappings=[invalid],
        unresolved_skills=[],
    )

    with pytest.raises(ProjectProfileBuildError, match=message):
        ProjectProfileBuilder().build(
            request=request(),
            extraction=extraction([source]),
            normalization=normalization,
        )


def test_empty_inputs_produce_empty_profile_and_preserve_metadata() -> None:
    profile = build_project_profile(
        request=request(),
        extraction=extraction([]),
        normalization=TaxonomyNormalizationResult(mappings=[]),
    )

    assert profile.request_id == "req-profile-001"
    assert profile.project_summary == "A deterministic profile builder test."
    assert profile.requirements == []
    assert profile.unresolved_skills == []
    assert profile.unresolved_requirements == []


def test_builder_does_not_mutate_any_input() -> None:
    input_request = request()
    input_extraction = extraction([requirement("Python"), requirement("Unknown")])
    input_normalization = TaxonomyNormalizationResult(
        mappings=[
            unresolved_mapping(1, "Unknown"),
            resolved_mapping(0, "Python", "python", "Python"),
        ]
    )
    before = (
        input_request.model_dump(),
        input_extraction.model_dump(),
        input_normalization.model_dump(),
    )

    ProjectProfileBuilder().build(
        request=input_request,
        extraction=input_extraction,
        normalization=input_normalization,
    )

    assert input_request.model_dump() == before[0]
    assert input_extraction.model_dump() == before[1]
    assert input_normalization.model_dump() == before[2]
