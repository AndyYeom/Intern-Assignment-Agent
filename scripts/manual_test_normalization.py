"""Evaluate Step 5 taxonomy normalization against versioned manual cases.

This opt-in runner calls the configured OpenAI model only for skills that do
not resolve deterministically and may incur API usage charges.
"""

import argparse
import asyncio
import json
from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    ExtractedRequirement,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomySelection,
    TaxonomySkill,
)
from project_catalog_agent.config.settings import Settings
from project_catalog_agent.llm import OpenAIStructuredLLMClient
from project_catalog_agent.taxonomy import (
    HybridTaxonomyNormalizer,
    JsonTaxonomyRepository,
    LLMTaxonomyMappingSelector,
    TaxonomyMappingSelector,
)
from project_catalog_agent.taxonomy.artifacts import sanitize_artifact_component
from project_catalog_agent.taxonomy.evaluation import (
    CaseEvaluation,
    EvaluationMetrics,
    NormalizationCase,
    NormalizationCaseSuite,
    calculate_metrics,
    compare_case_result,
    has_safety_failure,
)

DEFAULT_CASES_PATH = Path("tests/manual/normalization_cases.json")


class RecordingSelector:
    """Record selector proposals while delegating to the real implementation."""

    def __init__(self, delegate: TaxonomyMappingSelector) -> None:
        """Configure the selector to observe."""
        self._delegate = delegate
        self.call_count = 0
        self.last_selection: TaxonomySelection | None = None

    async def select(
        self,
        *,
        requirement: ExtractedRequirement,
        taxonomy_skills: tuple[TaxonomySkill, ...],
    ) -> TaxonomySelection:
        """Delegate selection and retain a detached proposal."""
        self.call_count += 1
        self.last_selection = None
        selection = await self._delegate.select(
            requirement=requirement,
            taxonomy_skills=taxonomy_skills,
        )
        self.last_selection = selection.model_copy(deep=True)
        return selection


def parse_arguments() -> argparse.Namespace:
    """Parse manual-evaluation command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="report ordinary expectation mismatches without failing the process",
    )
    return parser.parse_args()


def load_suite(path: Path) -> NormalizationCaseSuite:
    """Load and validate a versioned JSON case suite."""
    return NormalizationCaseSuite.model_validate_json(path.read_text(encoding="utf-8"))


def build_extraction(case: NormalizationCase) -> RequirementExtractionResult:
    """Create a controlled extraction containing exactly one raw skill."""
    return RequirementExtractionResult(
        project_summary=f"Manual normalization case {case.case_id}.",
        requirements=[
            ExtractedRequirement(
                raw_skill=case.raw_skill,
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=ProficiencyLevel.INTERMEDIATE,
                confidence=0.8,
                evidence_text=f"The project requires {case.raw_skill}.",
                decision_basis="Controlled input for taxonomy identity evaluation.",
            )
        ],
    )


async def evaluate_case(
    case: NormalizationCase,
    *,
    normalizer: HybridTaxonomyNormalizer,
    recording_selector: RecordingSelector,
    valid_skill_ids: set[str],
) -> CaseEvaluation:
    """Normalize and compare one case without stopping the remaining suite."""
    calls_before = recording_selector.call_count
    mapping = None
    error = None
    try:
        result = await normalizer.normalize(build_extraction(case))
        if len(result.mappings) != 1:
            error = f"expected one mapping, received {len(result.mappings)}"
        else:
            mapping = result.mappings[0]
    except Exception as caught_error:
        error = f"{type(caught_error).__name__}: {caught_error}"

    selector_called = recording_selector.call_count > calls_before
    selection = recording_selector.last_selection if selector_called else None
    proposed_ids = [
        *(
            [selection.selected_skill_id]
            if selection is not None and selection.selected_skill_id is not None
            else []
        ),
        *(selection.candidate_skill_ids if selection is not None else []),
    ]
    return compare_case_result(
        case,
        mapping,
        selector_called=selector_called,
        valid_skill_ids=valid_skill_ids,
        error=error,
        proposed_skill_ids=proposed_ids,
    )


def print_case_report(evaluation: CaseEvaluation) -> None:
    """Print a compact, readable report for one evaluated case."""
    outcome = "PASS" if evaluation.passed else "FAIL"
    actual = evaluation.actual
    print(f"[{outcome}] {evaluation.case_id}: {evaluation.raw_skill}")
    print(
        "  status: "
        f"expected={evaluation.expected_status.value} "
        f"actual={actual.status.value if actual.status else 'error'}"
    )
    print(
        "  method: "
        f"expected={evaluation.expected_match_method.value} "
        f"actual={actual.match_method.value if actual.match_method else 'error'}"
    )
    print(
        f"  skill_id: expected={evaluation.expected_skill_id} actual={actual.skill_id}"
    )
    if evaluation.expected_candidate_ids or actual.candidate_ids:
        print(
            f"  candidates: expected={sorted(evaluation.expected_candidate_ids)} "
            f"actual={sorted(actual.candidate_ids)}"
        )
    print(f"  selector_called: {actual.selector_called}")
    if actual.invented_ids:
        print(f"  invented_ids: {actual.invented_ids}")
    if actual.error:
        print(f"  error: {actual.error}")


def write_artifact(
    path: Path,
    *,
    evaluations: list[CaseEvaluation],
    metrics: EvaluationMetrics,
    model_name: str,
    taxonomy_version: str,
    test_suite_version: str,
) -> None:
    """Write a UTF-8 report artifact containing no credentials."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_suite_version": test_suite_version,
        "model_name": model_name,
        "taxonomy_version": taxonomy_version,
        "cases": [evaluation.model_dump(mode="json") for evaluation in evaluations],
        "metrics": metrics.model_dump(mode="json"),
    }
    path.write_text(
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )


async def run(arguments: argparse.Namespace) -> int:
    """Execute the suite, store its report, and return the process exit code."""
    suite = load_suite(arguments.cases)
    settings = Settings()
    model_name = arguments.model or settings.openai_model
    repository = JsonTaxonomyRepository()
    valid_skill_ids = {skill.skill_id for skill in repository.list_skills()}
    client = OpenAIStructuredLLMClient(
        api_key=settings.openai_api_key,
        model=model_name,
    )
    recording_selector = RecordingSelector(LLMTaxonomyMappingSelector(client))
    normalizer = HybridTaxonomyNormalizer(repository, recording_selector)
    evaluations: list[CaseEvaluation] = []

    for case in suite.cases:
        evaluation = await evaluate_case(
            case,
            normalizer=normalizer,
            recording_selector=recording_selector,
            valid_skill_ids=valid_skill_ids,
        )
        evaluations.append(evaluation)
        print_case_report(evaluation)

    metrics = calculate_metrics(evaluations)
    print("\nAggregate metrics")
    print(f"  cases: {metrics.case_count}")
    print(f"  passed: {metrics.passed_count}")
    print(f"  failed: {metrics.failed_count}")
    print(f"  status accuracy: {metrics.status_accuracy:.1%}")
    print(f"  canonical ID accuracy: {metrics.canonical_id_accuracy:.1%}")
    print(f"  match-method accuracy: {metrics.match_method_accuracy:.1%}")
    print(f"  unsafe forced-mapping rate: {metrics.unsafe_forced_mapping_rate:.1%}")
    print(f"  unnecessary LLM-call rate: {metrics.unnecessary_llm_call_rate:.1%}")

    output_path = arguments.output or (
        Path("artifacts/normalization")
        / sanitize_artifact_component(model_name, fallback="model")
        / "manual-normalization.json"
    )
    write_artifact(
        output_path,
        evaluations=evaluations,
        metrics=metrics,
        model_name=model_name,
        taxonomy_version=repository.version,
        test_suite_version=suite.test_suite_version,
    )
    print(f"  artifact: {output_path}")

    if has_safety_failure(evaluations, metrics):
        return 1
    if metrics.failed_count and not arguments.report_only:
        return 1
    return 0


def main() -> int:
    """Run the asynchronous evaluator from a synchronous script entry point."""
    return asyncio.run(run(parse_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
