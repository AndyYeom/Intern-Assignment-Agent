"""Tests for the numbered Step 9 catalog-state runner."""

import pytest
from scripts.manual_test_catalog_state import (
    evaluate_cases,
    load_cases,
    run_selected,
    select_cases,
)


def test_all_supplied_state_cases_match_expectations() -> None:
    cases = load_cases()
    evaluations = evaluate_cases(cases)

    assert len(cases) == 16
    assert all(passed for _, passed, _ in evaluations)


def test_zero_selects_all_cases() -> None:
    cases = load_cases()

    assert select_cases(cases, 0) == cases


def test_positive_index_selects_one_case_and_resolves_dependencies() -> None:
    cases = load_cases()
    selected = select_cases(cases, 16)

    assert [item.test_case_id for item in selected] == ["STATE-016"]
    assert run_selected(cases, selected) == [True]


@pytest.mark.parametrize("case_index", [-1, 17])
def test_out_of_range_index_is_rejected(case_index: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 16"):
        select_cases(load_cases(), case_index)
