"""Tests for the numbered Step 7 manual validation runner."""

import pytest
from scripts.manual_test_profile_validation import (
    load_cases,
    run_case,
    select_cases,
)

from project_catalog_agent.profile import ProjectProfileValidator
from project_catalog_agent.taxonomy import JsonTaxonomyRepository


def test_all_supplied_validation_cases_match_expectations() -> None:
    cases = load_cases()
    validator = ProjectProfileValidator(taxonomy_repository=JsonTaxonomyRepository())

    assert len(cases) == 10
    assert all(run_case(validation_case, validator) for validation_case in cases)


def test_zero_selects_all_cases() -> None:
    cases = load_cases()

    assert select_cases(cases, 0) == cases


def test_positive_index_selects_one_case() -> None:
    cases = load_cases()

    assert [item.name for item in select_cases(cases, 3)] == [
        "VAL-003: hard requirement missing level"
    ]


@pytest.mark.parametrize("case_index", [-1, 11])
def test_out_of_range_index_is_rejected(case_index: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 10"):
        select_cases(load_cases(), case_index)
