"""Tests for the numbered Step 6 manual runner."""

from pathlib import Path

import pytest
from scripts.manual_test_profile_builder import load_cases, run_case, select_case


def test_supplied_build_cases_validate_and_match(tmp_path: Path) -> None:
    cases = load_cases(Path("tests/manual/profile_build_cases.json"))

    assert [item.case_id for item in cases] == [
        "BUILD-001",
        "BUILD-002",
        "BUILD-003",
        "BUILD-004",
        "BUILD-005",
    ]
    assert all(run_case(item, tmp_path) for item in cases)
    assert sorted(path.name for path in tmp_path.glob("*.json")) == [
        "BUILD-001.json",
        "BUILD-002.json",
        "BUILD-003.json",
        "BUILD-004.json",
    ]


def test_manual_build_case_uses_one_based_selection() -> None:
    cases = load_cases(Path("tests/manual/profile_build_cases.json"))

    assert select_case(cases, 2).case_id == "BUILD-002"


@pytest.mark.parametrize("case_number", [0, 6])
def test_invalid_manual_build_case_number_is_rejected(case_number: int) -> None:
    cases = load_cases(Path("tests/manual/profile_build_cases.json"))

    with pytest.raises(ValueError, match="between 1 and 5"):
        select_case(cases, case_number)
