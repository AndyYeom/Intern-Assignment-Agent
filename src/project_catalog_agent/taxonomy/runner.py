"""Run-level normalization orchestration with artifact recording."""

from dataclasses import dataclass
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.taxonomy.artifacts import NormalizationArtifactWriter
from project_catalog_agent.taxonomy.normalizer import TaxonomyNormalizer


@dataclass(frozen=True, slots=True)
class RecordedNormalization:
    """A successful normalization result and its persisted artifact path."""

    result: TaxonomyNormalizationResult
    artifact_path: Path


class ArtifactRecordingNormalizationRunner:
    """Normalize, persist the successful run, and then return its output."""

    def __init__(
        self,
        *,
        normalizer: TaxonomyNormalizer,
        artifact_writer: NormalizationArtifactWriter,
        extraction_model_name: str,
        normalization_model_name: str,
        taxonomy_version: str,
        proficiency_version: str,
    ) -> None:
        """Configure the normalizer, writer, and non-secret run metadata."""
        self._normalizer = normalizer
        self._artifact_writer = artifact_writer
        self._extraction_model_name = extraction_model_name
        self._normalization_model_name = normalization_model_name
        self._taxonomy_version = taxonomy_version
        self._proficiency_version = proficiency_version

    async def run(
        self,
        *,
        request: CreateProjectRequest,
        extraction: RequirementExtractionResult,
    ) -> RecordedNormalization:
        """Save a validated artifact immediately after successful normalization."""
        result = await self._normalizer.normalize(extraction)
        artifact_path = self._artifact_writer.write(
            request=request,
            extraction_result=extraction,
            normalization_result=result,
            extraction_model_name=self._extraction_model_name,
            normalization_model_name=self._normalization_model_name,
            taxonomy_version=self._taxonomy_version,
            proficiency_version=self._proficiency_version,
        )
        return RecordedNormalization(result=result, artifact_path=artifact_path)
