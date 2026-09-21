"""Fixture tests for the controlled normalization-only project examples."""

from pathlib import Path

import pytest
from scripts.manual_test_project_normalization import load_suite

from project_catalog_agent.catalog.contracts import (
    MappingStatus,
    MatchMethod,
    TaxonomyCandidate,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.profile import ProjectProfileBuilder


def resolved(
    index: int,
    raw_skill: str,
    skill_id: str,
    canonical_name: str,
    method: MatchMethod,
) -> TaxonomyMapping:
    """Build a fixture resolved mapping."""
    return TaxonomyMapping(
        source_requirement_index=index,
        raw_skill=raw_skill,
        status=MappingStatus.RESOLVED,
        match_method=method,
        skill_id=skill_id,
        canonical_skill=canonical_name,
        decision_basis="Controlled fixture taxonomy decision.",
    )


def unresolved(
    index: int,
    raw_skill: str,
    *,
    status: MappingStatus = MappingStatus.UNMAPPED,
    candidates: tuple[str, ...] = (),
) -> TaxonomyMapping:
    """Build a fixture unresolved mapping."""
    return TaxonomyMapping(
        source_requirement_index=index,
        raw_skill=raw_skill,
        status=status,
        match_method=MatchMethod.UNRESOLVED,
        candidates=[
            TaxonomyCandidate(skill_id=value, canonical_name=value.title())
            for value in candidates
        ],
        decision_basis="Controlled fixture unresolved decision.",
    )


def fixture_mappings(case_number: int) -> list[TaxonomyMapping]:
    """Return controlled Step 5 outputs for the selected manual example."""
    if case_number == 1:
        return [
            resolved(0, "Python", "python", "Python", MatchMethod.EXACT),
            resolved(1, "FastAPI", "flask-fastapi", "Flask/FastAPI", MatchMethod.ALIAS),
            resolved(
                2, "REST APIs", "rest-api", "REST API Design", MatchMethod.LLM_SELECTED
            ),
            resolved(3, "PostgreSQL", "postgresql", "PostgreSQL", MatchMethod.EXACT),
            resolved(4, "React", "react", "React", MatchMethod.EXACT),
        ]
    if case_number == 2:
        return [
            resolved(0, "Python", "python", "Python", MatchMethod.EXACT),
            resolved(
                1,
                "retrieval-augmented generation",
                "rag",
                "RAG & Vector Search",
                MatchMethod.ALIAS,
            ),
            resolved(2, "embeddings", "rag", "RAG & Vector Search", MatchMethod.ALIAS),
            resolved(
                3,
                "vector search",
                "rag",
                "RAG & Vector Search",
                MatchMethod.LLM_SELECTED,
            ),
            resolved(4, "FAISS", "rag", "RAG & Vector Search", MatchMethod.ALIAS),
        ]
    if case_number == 4:
        return [
            unresolved(0, "Performance Profiling"),
            unresolved(1, "Performance Optimization"),
            resolved(2, "Python", "python", "Python", MatchMethod.EXACT),
            resolved(
                3,
                "Machine Learning",
                "machine-learning",
                "Machine Learning",
                MatchMethod.EXACT,
            ),
        ]
    if case_number == 5:
        return [
            unresolved(
                0,
                "React Native, Flutter, or native iOS and Android development",
                status=MappingStatus.NEEDS_REVIEW,
                candidates=("react-native", "flutter", "native-mobile"),
            ),
            unresolved(
                1,
                "AWS, Azure, or GCP",
                status=MappingStatus.NEEDS_REVIEW,
                candidates=("aws", "gcp-azure"),
            ),
        ]
    if case_number == 6:
        return [
            unresolved(0, "LLM Response Evaluation"),
            resolved(
                1,
                "LLM APIs",
                "llm-apps",
                "LLM Application Development",
                MatchMethod.LLM_SELECTED,
            ),
        ]
    raise AssertionError(f"no fixture mappings for case {case_number}")


@pytest.mark.parametrize(
    ("case_number", "resolved_ids", "unresolved_skills"),
    [
        (
            1,
            ["python", "flask-fastapi", "rest-api", "postgresql", "react"],
            [],
        ),
        (
            2,
            ["python", "rag"],
            [],
        ),
        (
            4,
            ["python", "machine-learning"],
            ["Performance Profiling", "Performance Optimization"],
        ),
        (
            5,
            [],
            [
                "React Native, Flutter, or native iOS and Android development",
                "AWS, Azure, or GCP",
            ],
        ),
        (
            6,
            ["llm-apps"],
            ["LLM Response Evaluation"],
        ),
    ],
)
def test_controlled_manual_profile_examples(
    case_number: int,
    resolved_ids: list[str],
    unresolved_skills: list[str],
) -> None:
    suite = load_suite(Path("tests/manual/normalization_project_cases.json"))
    project_case = suite.cases[case_number - 1]

    profile = ProjectProfileBuilder().build(
        request=project_case.request,
        extraction=project_case.extraction,
        normalization=TaxonomyNormalizationResult(
            mappings=fixture_mappings(case_number)
        ),
    )

    assert [item.skill_id for item in profile.requirements] == resolved_ids
    assert profile.unresolved_skills == unresolved_skills
    if case_number == 2:
        assert len(profile.requirements[1].provenance) == 4
    if case_number == 5:
        assert all(
            item.mapping_status is MappingStatus.NEEDS_REVIEW
            for item in profile.unresolved_requirements
        )
