"""Tests for extraction contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    ExtractedRequirement,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
)


def make_requirement(**overrides: object) -> ExtractedRequirement:
    """Build an extracted requirement with optional field overrides."""
    data: dict[str, object] = {
        "raw_skill": "Python",
        "importance": RequirementImportance.HARD_REQUIREMENT,
        "required_level": ProficiencyLevel.INTERMEDIATE,
        "confidence": 0.9,
        "evidence_text": "Strong Python programming is required.",
        "decision_basis": "The project requires independent feature development.",
    }
    data.update(overrides)
    return ExtractedRequirement.model_validate(data)


def test_valid_requirement() -> None:
    requirement = make_requirement()

    assert requirement.raw_skill == "Python"
    assert requirement.importance is RequirementImportance.HARD_REQUIREMENT
    assert requirement.required_level is ProficiencyLevel.INTERMEDIATE


@pytest.mark.parametrize("level", list(ProficiencyLevel))
def test_all_proficiency_levels_are_accepted(level: ProficiencyLevel) -> None:
    requirement = make_requirement(required_level=level)

    assert requirement.required_level is level


@pytest.mark.parametrize("level", [0, 4])
def test_invalid_required_level_is_rejected(level: int) -> None:
    with pytest.raises(ValidationError):
        make_requirement(required_level=level)


def test_required_level_is_required() -> None:
    with pytest.raises(ValidationError):
        ExtractedRequirement.model_validate(
            {
                "raw_skill": "Python",
                "importance": RequirementImportance.HARD_REQUIREMENT,
                "confidence": 0.9,
                "evidence_text": "Strong Python programming is required.",
                "decision_basis": "The work requires intermediate proficiency.",
            }
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_outside_range_is_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        make_requirement(confidence=confidence)


@pytest.mark.parametrize(
    "legacy_field", ["required_entry_level", "target_project_level"]
)
def test_legacy_level_fields_are_rejected(legacy_field: str) -> None:
    with pytest.raises(ValidationError):
        make_requirement(**{legacy_field: 2})


def test_blank_decision_basis_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_requirement(decision_basis="   ")


def test_blank_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_requirement(evidence_text="   ")


def test_unexpected_output_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_requirement(canonical_skill_id="python")


def test_extraction_list_defaults_are_not_shared() -> None:
    first = RequirementExtractionResult(project_summary="First", requirements=[])
    second = RequirementExtractionResult(project_summary="Second", requirements=[])

    first.uncertainties.append("Unknown framework")

    assert second.uncertainties == []
