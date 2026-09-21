"""Tests for taxonomy contracts."""

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    MappingStatus,
    MatchMethod,
    TaxonomyMapping,
    TaxonomySelection,
    TaxonomySkill,
)


def test_valid_resolved_mapping() -> None:
    mapping = TaxonomyMapping(
        source_requirement_index=0,
        raw_skill="Py",
        status=MappingStatus.RESOLVED,
        skill_id="python",
        canonical_skill="Python",
        match_method=MatchMethod.ALIAS,
        decision_basis="Matched the py alias.",
    )

    assert mapping.skill_id == "python"
    assert mapping.canonical_name == "Python"
    assert mapping.match_score is None


def test_valid_unmapped_mapping() -> None:
    mapping = TaxonomyMapping(
        source_requirement_index=0,
        raw_skill="Unknown tool",
        status=MappingStatus.UNMAPPED,
        match_method=MatchMethod.UNRESOLVED,
        decision_basis="No equivalent exists.",
    )

    assert mapping.skill_id is None
    assert mapping.canonical_skill is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"canonical_skill": "Python"},
        {"skill_id": "python"},
        {
            "skill_id": "python",
            "canonical_skill": "Python",
            "status": MappingStatus.UNMAPPED,
        },
        {"status": MappingStatus.NEEDS_REVIEW},
    ],
)
def test_inconsistent_mapping_is_rejected(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "source_requirement_index": 0,
        "raw_skill": "Python",
        "status": MappingStatus.RESOLVED,
        "match_method": MatchMethod.EXACT,
        "decision_basis": "Test basis.",
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        TaxonomyMapping.model_validate(values)


@pytest.mark.parametrize("match_score", [-0.1, 1.1])
def test_invalid_mapping_score_is_rejected(match_score: float) -> None:
    with pytest.raises(ValidationError):
        TaxonomyMapping(
            source_requirement_index=0,
            raw_skill="Unknown tool",
            status=MappingStatus.UNMAPPED,
            match_method=MatchMethod.UNRESOLVED,
            match_score=match_score,
            decision_basis="No equivalent exists.",
        )


def test_negative_source_index_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaxonomyMapping(
            source_requirement_index=-1,
            raw_skill="Unknown tool",
            status=MappingStatus.UNMAPPED,
            match_method=MatchMethod.UNRESOLVED,
            decision_basis="No equivalent exists.",
        )


@pytest.mark.parametrize(
    "values",
    [
        {"decision": "select"},
        {"decision": "needs_review", "candidate_skill_ids": ["python"]},
        {
            "decision": "needs_review",
            "selected_skill_id": "python",
            "candidate_skill_ids": ["python", "sql"],
        },
        {"decision": "unmapped", "selected_skill_id": "python"},
    ],
)
def test_invalid_taxonomy_selection_is_rejected(values: dict[str, object]) -> None:
    values["decision_basis"] = "Test basis."
    with pytest.raises(ValidationError):
        TaxonomySelection.model_validate(values)


def test_blank_taxonomy_alias_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaxonomySkill(
            skill_id="python",
            canonical_name="Python",
            aliases=["   "],
            category="Programming language",
        )


def test_taxonomy_list_defaults_are_not_shared() -> None:
    first = TaxonomySkill(
        skill_id="python",
        canonical_name="Python",
        category="Programming language",
    )
    second = TaxonomySkill(
        skill_id="sql",
        canonical_name="SQL",
        category="Query language",
    )

    first.aliases.append("Py")

    assert second.aliases == []
