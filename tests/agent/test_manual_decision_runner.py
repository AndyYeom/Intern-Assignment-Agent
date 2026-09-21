"""Tests for the numbered Step 10 manual decision runner."""

import pytest
from scripts.manual_test_decision_policy import load_cases, run_case, select_cases


def test_all_supplied_decision_cases_match() -> None:
    cases = load_cases()
    assert len(cases) == 25
    assert all(run_case(case) for case in cases)


def test_zero_selects_all_and_positive_index_selects_one() -> None:
    cases = load_cases()
    assert select_cases(cases, 0) == cases
    assert select_cases(cases, 23)[0]["test_case_id"] == "DEC-023"


@pytest.mark.parametrize("index", [-1, 26])
def test_invalid_index_is_rejected(index: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 25"):
        select_cases(load_cases(), index)
