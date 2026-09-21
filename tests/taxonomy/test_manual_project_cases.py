"""Tests for the normalization-only controlled project cases."""

from pathlib import Path

import pytest
from scripts.manual_test_project_normalization import load_suite, select_case


def test_six_controlled_project_cases_are_valid() -> None:
    suite = load_suite(Path("tests/manual/normalization_project_cases.json"))

    assert suite.test_suite_version == "1.0.0"
    assert len(suite.cases) == 6
    assert [item.request.request_id for item in suite.cases] == [
        "NORM-MANUAL-001",
        "NORM-MANUAL-002",
        "NORM-MANUAL-003",
        "NORM-MANUAL-004",
        "NORM-MANUAL-005",
        "NORM-MANUAL-006",
    ]
    assert all(item.extraction.requirements for item in suite.cases)


def test_case_can_be_selected_by_one_based_number() -> None:
    suite = load_suite(Path("tests/manual/normalization_project_cases.json"))

    selected = select_case(suite, 4)

    assert selected.request.request_id == "NORM-MANUAL-004"


@pytest.mark.parametrize("case_number", [0, 7])
def test_out_of_range_case_number_is_rejected(case_number: int) -> None:
    suite = load_suite(Path("tests/manual/normalization_project_cases.json"))

    with pytest.raises(ValueError, match="between 1 and 6"):
        select_case(suite, case_number)
