"""Filesystem artifact storage for opt-in extraction runs."""

import json
import re
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
)

DEFAULT_EXTRACTION_ARTIFACT_DIRECTORY = Path("artifacts/extraction")


def sanitize_request_id(request_id: str) -> str:
    """Convert a request ID into a safe, portable filename stem."""
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", request_id)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_-")
    return sanitized or "request"


class ExtractionArtifactWriter:
    """Write validated manual extraction inputs and outputs as JSON."""

    def __init__(
        self,
        output_directory: Path = DEFAULT_EXTRACTION_ARTIFACT_DIRECTORY,
    ) -> None:
        """Configure the output directory without creating it yet."""
        self._output_directory = output_directory

    def write(
        self,
        *,
        request: CreateProjectRequest,
        result: RequirementExtractionResult,
        model_name: str,
        taxonomy_version: str,
        proficiency_version: str,
    ) -> Path:
        """Store one UTF-8 JSON artifact for a request and validated result."""
        validated_request = CreateProjectRequest.model_validate(request.model_dump())
        validated_result = RequirementExtractionResult.model_validate(
            result.model_dump()
        )
        numbered_directory = self._create_numbered_directory()
        filename = f"{sanitize_request_id(validated_request.request_id)}.json"
        artifact_path = numbered_directory / filename
        payload = {
            "request": validated_request.model_dump(mode="json"),
            "result": validated_result.model_dump(mode="json"),
            "model_name": model_name,
            "taxonomy_version": taxonomy_version,
            "proficiency_version": proficiency_version,
        }
        artifact_path.write_text(
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n",
            encoding="utf-8",
        )
        return artifact_path

    def _create_numbered_directory(self) -> Path:
        """Create and return the next available zero-padded directory."""
        self._output_directory.mkdir(parents=True, exist_ok=True)
        existing_numbers = [
            int(path.name)
            for path in self._output_directory.iterdir()
            if path.is_dir() and path.name.isdigit()
        ]
        next_number = max(existing_numbers, default=0) + 1

        while True:
            candidate = self._output_directory / f"{next_number:03d}"
            try:
                candidate.mkdir()
            except FileExistsError:
                next_number += 1
            else:
                return candidate
