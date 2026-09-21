"""Tests for manual extraction artifact storage."""

import json
from pathlib import Path

import pytest

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
)
from project_catalog_agent.extraction import (
    ExtractionArtifactWriter,
    sanitize_request_id,
)


def make_request(request_id: str = "REQ-001") -> CreateProjectRequest:
    """Build a request containing Unicode text."""
    return CreateProjectRequest(
        request_id=request_id,
        project_name="Analyse de données café",
        project_description="Créer une API Python pour analyser les données.",
    )


def make_result() -> RequirementExtractionResult:
    """Build a validated extraction result containing Unicode text."""
    return RequirementExtractionResult(
        project_summary="Analyse des données pour l'équipe.",
        requirements=[
            ExtractedRequirement(
                raw_skill="Python",
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=ProficiencyLevel.INTERMEDIATE,
                evidence_text="Créer une API Python",
                decision_basis="La réalisation indépendante exige ce niveau.",
                confidence=0.9,
            )
        ],
    )


@pytest.mark.parametrize(
    ("request_id", "expected"),
    [
        ("REQ-001", "REQ-001"),
        ("../REQ / test:01", "REQ_test_01"),
        ("spaces and/slashes", "spaces_and_slashes"),
        ("...", "request"),
    ],
)
def test_request_id_filename_sanitization(
    request_id: str,
    expected: str,
) -> None:
    assert sanitize_request_id(request_id) == expected


def test_writer_creates_output_directory_and_safe_filename(tmp_path: Path) -> None:
    output_directory = tmp_path / "nested" / "artifacts"
    writer = ExtractionArtifactWriter(output_directory)

    artifact_path = writer.write(
        request=make_request("../REQ / 001"),
        result=make_result(),
        model_name="test-model",
        taxonomy_version="0.1",
        proficiency_version="0.1",
    )

    assert output_directory.is_dir()
    assert artifact_path == output_directory / "001" / "REQ_001.json"
    assert artifact_path.is_file()


def test_writer_uses_next_numbered_directory(tmp_path: Path) -> None:
    (tmp_path / "001").mkdir()
    writer = ExtractionArtifactWriter(tmp_path)

    second_path = writer.write(
        request=make_request("REQ-002"),
        result=make_result(),
        model_name="test-model",
        taxonomy_version="0.1",
        proficiency_version="0.1",
    )
    third_path = writer.write(
        request=make_request("REQ-003"),
        result=make_result(),
        model_name="test-model",
        taxonomy_version="0.1",
        proficiency_version="0.1",
    )

    assert second_path == tmp_path / "002" / "REQ-002.json"
    assert third_path == tmp_path / "003" / "REQ-003.json"


def test_artifact_contains_request_result_and_version_metadata(
    tmp_path: Path,
) -> None:
    request = make_request()
    result = make_result()
    writer = ExtractionArtifactWriter(tmp_path)

    artifact_path = writer.write(
        request=request,
        result=result,
        model_name="test-model",
        taxonomy_version="0.1",
        proficiency_version="0.1",
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert payload == {
        "request": request.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "model_name": "test-model",
        "taxonomy_version": "0.1",
        "proficiency_version": "0.1",
    }


def test_artifact_preserves_unicode_as_utf8(tmp_path: Path) -> None:
    writer = ExtractionArtifactWriter(tmp_path)

    artifact_path = writer.write(
        request=make_request(),
        result=make_result(),
        model_name="test-model",
        taxonomy_version="0.1",
        proficiency_version="0.1",
    )
    content = artifact_path.read_text(encoding="utf-8")

    assert "données café" in content
    assert "équipe" in content
    assert "\\u00e9" not in content


def test_artifact_never_contains_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")
    writer = ExtractionArtifactWriter(tmp_path)

    artifact_path = writer.write(
        request=make_request(),
        result=make_result(),
        model_name="test-model",
        taxonomy_version="0.1",
        proficiency_version="0.1",
    )
    content = artifact_path.read_text(encoding="utf-8")

    assert "secret-test-key" not in content
    assert "api_key" not in content.casefold()
