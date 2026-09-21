"""Filesystem artifact storage for opt-in normalization runs."""

import json
import re
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
)

DEFAULT_NORMALIZATION_ARTIFACT_DIRECTORY = Path("artifacts/normalization")


def sanitize_artifact_component(value: str, *, fallback: str) -> str:
    """Convert an untrusted value into a safe portable path component."""
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    sanitized = re.sub(r"_+", "_", sanitized).strip("._-")
    return sanitized or fallback


class NormalizationArtifactWriter:
    """Write validated manual normalization inputs and outputs as JSON."""

    def __init__(
        self,
        output_directory: Path = DEFAULT_NORMALIZATION_ARTIFACT_DIRECTORY,
    ) -> None:
        """Configure the output directory without creating it yet."""
        self._output_directory = output_directory

    def write(
        self,
        *,
        request: CreateProjectRequest,
        extraction_result: RequirementExtractionResult,
        normalization_result: TaxonomyNormalizationResult,
        extraction_model_name: str,
        normalization_model_name: str,
        taxonomy_version: str,
        proficiency_version: str,
    ) -> Path:
        """Store one UTF-8 JSON artifact under model name and request ID."""
        validated_request = CreateProjectRequest.model_validate(request.model_dump())
        validated_extraction = RequirementExtractionResult.model_validate(
            extraction_result.model_dump()
        )
        validated_normalization = TaxonomyNormalizationResult.model_validate(
            normalization_result.model_dump()
        )
        model_directory = self._output_directory / sanitize_artifact_component(
            normalization_model_name,
            fallback="model",
        )
        model_directory.mkdir(parents=True, exist_ok=True)
        request_stem = sanitize_artifact_component(
            validated_request.request_id,
            fallback="request",
        )
        artifact_path = model_directory / f"{request_stem}.json"
        payload = {
            "request": validated_request.model_dump(mode="json"),
            "extraction_result": validated_extraction.model_dump(mode="json"),
            "normalization_result": validated_normalization.model_dump(mode="json"),
            "extraction_model_name": extraction_model_name,
            "normalization_model_name": normalization_model_name,
            "taxonomy_version": taxonomy_version,
            "proficiency_version": proficiency_version,
        }
        artifact_path.write_text(
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n",
            encoding="utf-8",
        )
        return artifact_path
