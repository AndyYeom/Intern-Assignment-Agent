"""Tests for project profile contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    ProficiencyLevel,
    ProjectProfile,
    ProjectRequirement,
    RequirementImportance,
)


def make_requirement(**overrides: object) -> ProjectRequirement:
    """Build a normalized project requirement."""
    data: dict[str, object] = {
        "skill_id": "python",
        "canonical_name": "Python",
        "importance": RequirementImportance.HARD_REQUIREMENT,
        "required_level": ProficiencyLevel.INTERMEDIATE,
        "evidence_text": "Python is required.",
        "confidence": 0.9,
        "decision_basis": "The implementation requires routine Python work.",
    }
    data.update(overrides)
    return ProjectRequirement.model_validate(data)


def make_profile(**overrides: object) -> ProjectProfile:
    """Build a project profile."""
    data: dict[str, object] = {
        "request_id": "req-001",
        "project_name": "Recommendation Engine",
        "project_description": "Build a recommendation engine.",
        "project_summary": "A content recommendation project.",
        "requirements": [make_requirement()],
    }
    data.update(overrides)
    return ProjectProfile.model_validate(data)


def test_valid_profile() -> None:
    profile = make_profile()

    assert profile.requirements[0].skill_id == "python"
    assert profile.requirements[0].required_level is ProficiencyLevel.INTERMEDIATE


def test_empty_requirements_are_accepted() -> None:
    profile = make_profile(requirements=[])

    assert profile.requirements == []


def test_invalid_nested_requirement_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_profile(
            requirements=[
                {
                    "skill_id": "",
                    "canonical_name": "Python",
                    "importance": "hard_requirement",
                    "required_level": 2,
                    "evidence_text": "Python is required.",
                    "confidence": 0.9,
                    "decision_basis": "Python is central to the implementation.",
                }
            ]
        )


@pytest.mark.parametrize(
    "legacy_field", ["required_entry_level", "target_project_level"]
)
def test_legacy_requirement_level_fields_are_rejected(legacy_field: str) -> None:
    requirement_data = make_requirement().model_dump()
    requirement_data[legacy_field] = 2

    with pytest.raises(ValidationError):
        ProjectRequirement.model_validate(requirement_data)


def test_unexpected_profile_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_profile(database_id=42)


def test_profile_list_defaults_are_not_shared() -> None:
    first = make_profile()
    second = make_profile()

    first.unresolved_skills.append("COBOL")
    first.requirements[0].provenance.append(
        {
            "source_requirement_index": 0,
            "raw_skill": "Python",
            "importance": "hard_requirement",
            "required_level": 2,
            "evidence_text": "Python is required.",
            "extraction_decision_basis": "Python is required.",
            "extraction_confidence": 0.9,
            "match_method": "exact",
            "taxonomy_decision_basis": "Matched Python.",
        }
    )

    assert second.unresolved_skills == []
    assert second.requirements[0].provenance == []
    assert second.unresolved_requirements == []
