"""Tests for normalization orchestration with automatic artifact recording."""

import asyncio
import json
from pathlib import Path

import pytest

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.taxonomy import (
    ArtifactRecordingNormalizationRunner,
    HybridTaxonomyNormalizer,
    JsonTaxonomyRepository,
    NormalizationArtifactWriter,
)


def request() -> CreateProjectRequest:
    """Build one controlled project request."""
    return CreateProjectRequest(
        request_id="pipeline-001",
        project_name="Pipeline test",
        project_description="Python is required.",
    )


def extraction() -> RequirementExtractionResult:
    """Build one deterministically resolvable extraction result."""
    return RequirementExtractionResult(
        project_summary="Pipeline normalization test.",
        requirements=[
            ExtractedRequirement(
                raw_skill="Python",
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=ProficiencyLevel.INTERMEDIATE,
                confidence=0.99,
                evidence_text="Python is required.",
                decision_basis="Python is explicitly required.",
            )
        ],
    )


def test_runner_saves_artifact_before_returning_result(tmp_path: Path) -> None:
    repository = JsonTaxonomyRepository()
    runner = ArtifactRecordingNormalizationRunner(
        normalizer=HybridTaxonomyNormalizer(repository),
        artifact_writer=NormalizationArtifactWriter(tmp_path),
        extraction_model_name="controlled-input",
        normalization_model_name="test-model",
        taxonomy_version=repository.version,
        proficiency_version="1.0",
    )

    recorded = asyncio.run(runner.run(request=request(), extraction=extraction()))

    assert recorded.result.mappings[0].skill_id == "python"
    assert recorded.artifact_path.exists()
    payload = json.loads(recorded.artifact_path.read_text(encoding="utf-8"))
    assert payload["normalization_result"]["mappings"][0]["skill_id"] == "python"
    assert payload["extraction_model_name"] == "controlled-input"


class FailingNormalizer:
    """Normalizer that simulates a failed pipeline stage."""

    async def normalize(
        self,
        extraction: RequirementExtractionResult,
    ) -> TaxonomyNormalizationResult:
        """Fail without returning a normalization result."""
        raise RuntimeError("normalization failed")


def test_runner_does_not_write_artifact_when_normalization_fails(
    tmp_path: Path,
) -> None:
    runner = ArtifactRecordingNormalizationRunner(
        normalizer=FailingNormalizer(),
        artifact_writer=NormalizationArtifactWriter(tmp_path),
        extraction_model_name="controlled-input",
        normalization_model_name="test-model",
        taxonomy_version="1.0",
        proficiency_version="1.0",
    )

    with pytest.raises(RuntimeError, match="normalization failed"):
        asyncio.run(runner.run(request=request(), extraction=extraction()))

    assert list(tmp_path.iterdir()) == []
