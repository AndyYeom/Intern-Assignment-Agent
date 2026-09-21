"""Tests for the numbered Step 8 manual recovery runner."""

import asyncio

import pytest
from scripts.manual_test_recovery_actions import load_cases, run_case, select_cases


def test_all_supplied_recovery_cases_match_expectations() -> None:
    cases = load_cases()

    results = asyncio.run(_run_all(cases))

    assert len(cases) == 13
    assert all(results)


async def _run_all(cases):  # type: ignore[no-untyped-def]
    return [await run_case(recovery_case) for recovery_case in cases]


def test_zero_selects_all_cases() -> None:
    cases = load_cases()

    assert select_cases(cases, 0) == cases


def test_positive_index_selects_one_case() -> None:
    cases = load_cases()

    assert [item.test_case_id for item in select_cases(cases, 8)] == ["REC-008"]


@pytest.mark.parametrize("case_index", [-1, 14])
def test_out_of_range_index_is_rejected(case_index: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 13"):
        select_cases(load_cases(), case_index)
