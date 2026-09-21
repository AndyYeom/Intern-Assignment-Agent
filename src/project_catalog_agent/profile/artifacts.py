"""Filesystem artifact storage for successful project-profile builds."""

import json
import re
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ProjectProfile,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
)

DEFAULT_PROFILE_ARTIFACT_DIRECTORY = Path("artifacts/profile")
PROFILE_BUILDER_VERSION = "1.0.0"


def sanitize_profile_artifact_name(value: str) -> str:
    """Convert a request ID into a safe portable filename stem."""
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    sanitized = re.sub(r"_+", "_", sanitized).strip("._-")
    return sanitized or "request"


class ProfileArtifactWriter:
    """Persist validated profile-builder inputs and successful output."""

    def __init__(
        self,
        output_directory: Path = DEFAULT_PROFILE_ARTIFACT_DIRECTORY,
    ) -> None:
        """Configure the output directory without creating it yet."""
        self._output_directory = output_directory

    def write(
        self,
        *,
        request: CreateProjectRequest,
        extraction_result: RequirementExtractionResult,
        normalization_result: TaxonomyNormalizationResult,
        profile: ProjectProfile,
    ) -> Path:
        """Write one UTF-8 profile artifact containing no credentials."""
        validated_request = CreateProjectRequest.model_validate(request.model_dump())
        validated_extraction = RequirementExtractionResult.model_validate(
            extraction_result.model_dump()
        )
        validated_normalization = TaxonomyNormalizationResult.model_validate(
            normalization_result.model_dump()
        )
        validated_profile = ProjectProfile.model_validate(profile.model_dump())
        self._output_directory.mkdir(parents=True, exist_ok=True)
        artifact_path = self._output_directory / (
            f"{sanitize_profile_artifact_name(validated_request.request_id)}.json"
        )
        payload = {
            "request": validated_request.model_dump(mode="json"),
            "extraction_result": validated_extraction.model_dump(mode="json"),
            "normalization_result": validated_normalization.model_dump(mode="json"),
            "project_profile": validated_profile.model_dump(mode="json"),
            "profile_builder_version": PROFILE_BUILDER_VERSION,
        }
        artifact_path.write_text(
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n",
            encoding="utf-8",
        )
        return artifact_path
