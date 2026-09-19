"""Run-level profile construction with automatic artifact recording."""

from dataclasses import dataclass
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ProjectProfile,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.profile.artifacts import ProfileArtifactWriter
from project_catalog_agent.profile.builder import ProjectProfileBuilder


@dataclass(frozen=True, slots=True)
class RecordedProjectProfile:
    """A successfully built profile and its persisted artifact path."""

    profile: ProjectProfile
    artifact_path: Path


class ArtifactRecordingProjectProfileBuilder:
    """Build, persist the successful profile, and then return its output."""

    def __init__(
        self,
        *,
        builder: ProjectProfileBuilder,
        artifact_writer: ProfileArtifactWriter,
    ) -> None:
        """Configure the pure builder and external artifact writer."""
        self._builder = builder
        self._artifact_writer = artifact_writer

    def build(
        self,
        *,
        request: CreateProjectRequest,
        extraction: RequirementExtractionResult,
        normalization: TaxonomyNormalizationResult,
    ) -> RecordedProjectProfile:
        """Save an artifact immediately after a successful profile build."""
        profile = self._builder.build(
            request=request,
            extraction=extraction,
            normalization=normalization,
        )
        artifact_path = self._artifact_writer.write(
            request=request,
            extraction_result=extraction,
            normalization_result=normalization,
            profile=profile,
        )
        return RecordedProjectProfile(profile=profile, artifact_path=artifact_path)
