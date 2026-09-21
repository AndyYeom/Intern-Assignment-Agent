"""Tests for manual normalization comparison and metric calculations."""

import json
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    MappingStatus,
    MatchMethod,
    TaxonomyCandidate,
    TaxonomyMapping,
)
from project_catalog_agent.taxonomy.evaluation import (
    NormalizationCase,
    NormalizationCaseSuite,
    calculate_metrics,
    compare_case_result,
    has_safety_failure,
)

VALID_IDS = {"python", "postgresql", "data-modeling"}


def case(
    case_id: str,
    *,
    status: MappingStatus,
    method: MatchMethod,
    skill_id: str | None = None,
    candidates: list[str] | None = None,
) -> NormalizationCase:
    """Build one expected manual-evaluation case."""
    return NormalizationCase(
        case_id=case_id,
        raw_skill=case_id,
        expected_status=status,
        expected_match_method=method,
        expected_skill_id=skill_id,
        expected_candidate_ids=candidates or [],
    )


def mapping(
    raw_skill: str,
    *,
    status: MappingStatus,
    method: MatchMethod,
    skill_id: str | None = None,
    candidates: list[str] | None = None,
) -> TaxonomyMapping:
    """Build one fake normalization mapping."""
    return TaxonomyMapping(
        source_requirement_index=0,
        raw_skill=raw_skill,
        status=status,
        match_method=method,
        skill_id=skill_id,
        canonical_skill=skill_id.title() if skill_id is not None else None,
        candidates=[
            TaxonomyCandidate(skill_id=value, canonical_name=value.title())
            for value in candidates or []
        ],
        decision_basis="Controlled fake normalization output.",
    )


def test_candidate_comparison_uses_sets() -> None:
    expected = case(
        "compound",
        status=MappingStatus.NEEDS_REVIEW,
        method=MatchMethod.UNRESOLVED,
        candidates=["postgresql", "data-modeling"],
    )
    actual = mapping(
        "compound",
        status=MappingStatus.NEEDS_REVIEW,
        method=MatchMethod.UNRESOLVED,
        candidates=["data-modeling", "postgresql"],
    )

    evaluation = compare_case_result(
        expected,
        actual,
        selector_called=True,
        valid_skill_ids=VALID_IDS,
    )

    assert evaluation.candidate_ids_match is True
    assert evaluation.passed is True


def test_comparison_detects_invented_mapping_and_proposed_ids() -> None:
    expected = case(
        "unknown",
        status=MappingStatus.UNMAPPED,
        method=MatchMethod.UNRESOLVED,
    )
    actual = mapping(
        "unknown",
        status=MappingStatus.RESOLVED,
        method=MatchMethod.LLM_SELECTED,
        skill_id="invented",
    )

    evaluation = compare_case_result(
        expected,
        actual,
        selector_called=True,
        valid_skill_ids=VALID_IDS,
        proposed_skill_ids=["another-invented"],
    )

    assert evaluation.actual.invented_ids == ["invented", "another-invented"]
    assert evaluation.passed is False


def test_metrics_calculate_accuracy_and_safety_rates() -> None:
    exact_case = case(
        "exact",
        status=MappingStatus.RESOLVED,
        method=MatchMethod.EXACT,
        skill_id="python",
    )
    alias_case = case(
        "alias",
        status=MappingStatus.RESOLVED,
        method=MatchMethod.ALIAS,
        skill_id="python",
    )
    unmapped_case = case(
        "unsafe",
        status=MappingStatus.UNMAPPED,
        method=MatchMethod.UNRESOLVED,
    )
    review_case = case(
        "review",
        status=MappingStatus.NEEDS_REVIEW,
        method=MatchMethod.UNRESOLVED,
        candidates=["postgresql", "data-modeling"],
    )
    evaluations = [
        compare_case_result(
            exact_case,
            mapping(
                "exact",
                status=MappingStatus.RESOLVED,
                method=MatchMethod.EXACT,
                skill_id="python",
            ),
            selector_called=False,
            valid_skill_ids=VALID_IDS,
        ),
        compare_case_result(
            alias_case,
            mapping(
                "alias",
                status=MappingStatus.RESOLVED,
                method=MatchMethod.ALIAS,
                skill_id="python",
            ),
            selector_called=True,
            valid_skill_ids=VALID_IDS,
        ),
        compare_case_result(
            unmapped_case,
            mapping(
                "unsafe",
                status=MappingStatus.RESOLVED,
                method=MatchMethod.LLM_SELECTED,
                skill_id="python",
            ),
            selector_called=True,
            valid_skill_ids=VALID_IDS,
        ),
        compare_case_result(
            review_case,
            mapping(
                "review",
                status=MappingStatus.NEEDS_REVIEW,
                method=MatchMethod.UNRESOLVED,
                candidates=["data-modeling", "postgresql"],
            ),
            selector_called=True,
            valid_skill_ids=VALID_IDS,
        ),
    ]

    metrics = calculate_metrics(evaluations)

    assert metrics.status_accuracy == 0.75
    assert metrics.canonical_id_accuracy == 0.75
    assert metrics.match_method_accuracy == 0.75
    assert metrics.unsafe_forced_mapping_rate == 0.5
    assert metrics.unnecessary_llm_call_rate == 0.5
    assert metrics.passed_count == 2
    assert metrics.failed_count == 2
    assert has_safety_failure(evaluations, metrics) is True


def test_empty_metrics_are_zero_and_safe() -> None:
    metrics = calculate_metrics([])

    assert metrics.status_accuracy == 0.0
    assert metrics.canonical_id_accuracy == 0.0
    assert metrics.match_method_accuracy == 0.0
    assert metrics.unsafe_forced_mapping_rate == 0.0
    assert metrics.unnecessary_llm_call_rate == 0.0
    assert has_safety_failure([], metrics) is False


def test_manual_case_file_contains_twenty_valid_cases() -> None:
    path = Path("tests/manual/normalization_cases.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    suite = NormalizationCaseSuite.model_validate(payload)

    assert suite.test_suite_version == "1.0.0"
    assert len(suite.cases) == 20
    assert len({item.case_id for item in suite.cases}) == 20
