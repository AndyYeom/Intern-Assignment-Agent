"""Tests for profile artifacts and the artifact-recording builder."""

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
from project_catalog_agent.profile import (
    ArtifactRecordingProjectProfileBuilder,
    ProfileArtifactWriter,
    ProjectProfileBuilder,
)


def test_recording_builder_saves_profile_before_returning(tmp_path: Path) -> None:
    request = CreateProjectRequest(
        request_id="../BUILD / 001",
        project_name="Prüfprofil",
        project_description="Python ist erforderlich.",
    )
    extraction = RequirementExtractionResult(
        project_summary="Ein Python-Projekt.",
        requirements=[
            ExtractedRequirement(
                raw_skill="Python",
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=ProficiencyLevel.INTERMEDIATE,
                confidence=0.99,
                evidence_text="Python ist erforderlich.",
                decision_basis="Python is mandatory.",
            )
        ],
    )
    normalization = TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill="Python",
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id="python",
                canonical_skill="Python",
                decision_basis="Matched canonical name.",
            )
        ]
    )
    runner = ArtifactRecordingProjectProfileBuilder(
        builder=ProjectProfileBuilder(),
        artifact_writer=ProfileArtifactWriter(tmp_path / "profiles"),
    )

    recorded = runner.build(
        request=request,
        extraction=extraction,
        normalization=normalization,
    )

    assert recorded.artifact_path == tmp_path / "profiles/BUILD_001.json"
    assert recorded.artifact_path.exists()
    raw_text = recorded.artifact_path.read_text(encoding="utf-8")
    assert "Prüfprofil" in raw_text
    payload = json.loads(raw_text)
    assert payload["project_profile"]["requirements"][0]["skill_id"] == "python"
    assert payload["profile_builder_version"] == "1.0.0"
    assert "api_key" not in raw_text.casefold()
