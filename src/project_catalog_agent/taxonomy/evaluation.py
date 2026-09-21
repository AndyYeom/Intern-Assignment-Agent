"""Models and calculations for manual taxonomy-normalization evaluation."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from project_catalog_agent.catalog.contracts import (
    ContractModel,
    MappingStatus,
    MatchMethod,
    TaxonomyMapping,
)


class NormalizationCase(ContractModel):
    """One expected normalization outcome in the manual evaluation suite."""

    case_id: Annotated[str, Field(min_length=1)]
    raw_skill: Annotated[str, Field(min_length=1)]
    expected_status: MappingStatus
    expected_match_method: MatchMethod
    expected_skill_id: str | None = None
    expected_candidate_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_expectation(self) -> Self:
        """Ensure the expected identity agrees with the expected status."""
        if self.expected_status is MappingStatus.RESOLVED:
            if self.expected_skill_id is None:
                msg = "resolved cases require expected_skill_id"
                raise ValueError(msg)
        elif self.expected_skill_id is not None:
            msg = "unresolved cases cannot have expected_skill_id"
            raise ValueError(msg)
        if (
            self.expected_status is MappingStatus.NEEDS_REVIEW
            and len(set(self.expected_candidate_ids)) < 2
        ):
            msg = "needs-review cases require at least two candidate IDs"
            raise ValueError(msg)
        return self


class NormalizationCaseSuite(ContractModel):
    """Versioned collection of manual normalization cases."""

    test_suite_version: Annotated[str, Field(min_length=1)]
    cases: list[NormalizationCase]


class ActualNormalization(ContractModel):
    """Comparable actual result for one case, including safety observations."""

    status: MappingStatus | None = None
    match_method: MatchMethod | None = None
    skill_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    selector_called: bool
    invented_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class CaseEvaluation(ContractModel):
    """Expected and actual values plus individual comparison outcomes."""

    case_id: str
    raw_skill: str
    expected_status: MappingStatus
    expected_match_method: MatchMethod
    expected_skill_id: str | None = None
    expected_candidate_ids: list[str] = Field(default_factory=list)
    actual: ActualNormalization
    status_matches: bool
    canonical_id_matches: bool
    match_method_matches: bool
    candidate_ids_match: bool
    deterministic_call_ok: bool
    passed: bool


class EvaluationMetrics(ContractModel):
    """Aggregate accuracy and safety metrics for a manual run."""

    case_count: int
    status_accuracy: float
    canonical_id_accuracy: float
    match_method_accuracy: float
    unsafe_forced_mapping_rate: float
    unnecessary_llm_call_rate: float
    passed_count: int
    failed_count: int


def compare_case_result(
    case: NormalizationCase,
    mapping: TaxonomyMapping | None,
    *,
    selector_called: bool,
    valid_skill_ids: set[str],
    error: str | None = None,
    proposed_skill_ids: list[str] | None = None,
) -> CaseEvaluation:
    """Compare one mapping to its expectation and identify unknown IDs."""
    candidate_ids = (
        [candidate.skill_id for candidate in mapping.candidates]
        if mapping is not None
        else []
    )
    observed_ids = [
        skill_id
        for skill_id in (
            mapping.skill_id if mapping is not None else None,
            *candidate_ids,
            *(proposed_skill_ids or []),
        )
        if skill_id is not None
    ]
    invented_ids = list(
        dict.fromkeys(
            skill_id for skill_id in observed_ids if skill_id not in valid_skill_ids
        )
    )
    actual = ActualNormalization(
        status=mapping.status if mapping is not None else None,
        match_method=mapping.match_method if mapping is not None else None,
        skill_id=mapping.skill_id if mapping is not None else None,
        candidate_ids=candidate_ids,
        selector_called=selector_called,
        invented_ids=invented_ids,
        error=error,
    )
    status_matches = actual.status is case.expected_status
    canonical_id_matches = actual.skill_id == case.expected_skill_id
    method_matches = actual.match_method is case.expected_match_method
    candidate_ids_match = (
        set(actual.candidate_ids) == set(case.expected_candidate_ids)
        if case.expected_status is MappingStatus.NEEDS_REVIEW
        else True
    )
    deterministic_case = case.expected_match_method in {
        MatchMethod.EXACT,
        MatchMethod.ALIAS,
    }
    deterministic_call_ok = not (deterministic_case and selector_called)
    passed = all(
        (
            error is None,
            not invented_ids,
            status_matches,
            canonical_id_matches,
            method_matches,
            candidate_ids_match,
            deterministic_call_ok,
        )
    )
    return CaseEvaluation(
        case_id=case.case_id,
        raw_skill=case.raw_skill,
        expected_status=case.expected_status,
        expected_match_method=case.expected_match_method,
        expected_skill_id=case.expected_skill_id,
        expected_candidate_ids=case.expected_candidate_ids,
        actual=actual,
        status_matches=status_matches,
        canonical_id_matches=canonical_id_matches,
        match_method_matches=method_matches,
        candidate_ids_match=candidate_ids_match,
        deterministic_call_ok=deterministic_call_ok,
        passed=passed,
    )


def calculate_metrics(evaluations: list[CaseEvaluation]) -> EvaluationMetrics:
    """Calculate accuracy and safety rates over completed case evaluations."""
    case_count = len(evaluations)
    unresolved_cases = [
        evaluation
        for evaluation in evaluations
        if evaluation.expected_status
        in {MappingStatus.NEEDS_REVIEW, MappingStatus.UNMAPPED}
    ]
    deterministic_cases = [
        evaluation
        for evaluation in evaluations
        if evaluation.expected_match_method in {MatchMethod.EXACT, MatchMethod.ALIAS}
    ]
    unsafe_forced = sum(
        evaluation.actual.status is MappingStatus.RESOLVED
        for evaluation in unresolved_cases
    )
    unnecessary_calls = sum(
        evaluation.actual.selector_called for evaluation in deterministic_cases
    )

    return EvaluationMetrics(
        case_count=case_count,
        status_accuracy=_ratio(
            sum(evaluation.status_matches for evaluation in evaluations),
            case_count,
        ),
        canonical_id_accuracy=_ratio(
            sum(evaluation.canonical_id_matches for evaluation in evaluations),
            case_count,
        ),
        match_method_accuracy=_ratio(
            sum(evaluation.match_method_matches for evaluation in evaluations),
            case_count,
        ),
        unsafe_forced_mapping_rate=_ratio(unsafe_forced, len(unresolved_cases)),
        unnecessary_llm_call_rate=_ratio(
            unnecessary_calls,
            len(deterministic_cases),
        ),
        passed_count=sum(evaluation.passed for evaluation in evaluations),
        failed_count=sum(not evaluation.passed for evaluation in evaluations),
    )


def has_safety_failure(
    evaluations: list[CaseEvaluation],
    metrics: EvaluationMetrics,
) -> bool:
    """Return whether a run violates a mandatory normalization safety rule."""
    return (
        any(evaluation.actual.invented_ids for evaluation in evaluations)
        or metrics.unsafe_forced_mapping_rate > 0
        or metrics.unnecessary_llm_call_rate > 0
    )


def _ratio(numerator: int, denominator: int) -> float:
    """Return a stable zero for an empty metric population."""
    return numerator / denominator if denominator else 0.0
