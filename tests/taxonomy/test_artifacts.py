"""Tests for manual normalization artifact storage."""

import json
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.taxonomy.artifacts import (
    NormalizationArtifactWriter,
    sanitize_artifact_component,
)


def extraction_result() -> RequirementExtractionResult:
    """Build a validated extraction result containing Unicode."""
    return RequirementExtractionResult(
        project_summary="Assistant für Dokumente",
        requirements=[
            ExtractedRequirement(
                raw_skill="Python",
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=ProficiencyLevel.INTERMEDIATE,
                confidence=0.9,
                evidence_text="Développer avec Python.",
                decision_basis="Python is mandatory.",
            )
        ],
    )


def normalization_result() -> TaxonomyNormalizationResult:
    """Build a validated normalization result."""
    return TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill="Python",
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id="python",
                canonical_skill="Python",
                decision_basis="Matched the canonical taxonomy name.",
            )
        ]
    )


def test_writer_sanitizes_paths_creates_directories_and_preserves_unicode(
    tmp_path: Path,
) -> None:
    writer = NormalizationArtifactWriter(tmp_path / "nested" / "normalization")
    request = CreateProjectRequest(
        request_id="../REQ / 日本語 01",
        project_name="Dokumentenprüfung",
        project_description="Développer avec Python.",
    )

    path = writer.write(
        request=request,
        extraction_result=extraction_result(),
        normalization_result=normalization_result(),
        extraction_model_name="extract/model:1",
        normalization_model_name="map/model:2",
        taxonomy_version="2026.1",
        proficiency_version="1.0",
    )

    assert path == tmp_path / "nested/normalization/map_model_2/REQ_01.json"
    raw_text = path.read_text(encoding="utf-8")
    assert "Développer" in raw_text
    payload = json.loads(raw_text)
    assert payload["request"]["project_name"] == "Dokumentenprüfung"
    assert payload["extraction_result"]["requirements"][0]["raw_skill"] == "Python"
    assert payload["normalization_result"]["mappings"][0]["skill_id"] == "python"
    assert payload["extraction_model_name"] == "extract/model:1"
    assert payload["normalization_model_name"] == "map/model:2"
    assert payload["taxonomy_version"] == "2026.1"
    assert payload["proficiency_version"] == "1.0"
    assert "api_key" not in raw_text.casefold()


def test_empty_path_component_uses_fallback() -> None:
    assert sanitize_artifact_component("../", fallback="model") == "model"
