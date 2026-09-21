"""Run one or all controlled Step 8 recovery-action cases.

Enter 0 to run every case or select a one-based case index. The runner uses
controlled service responses and makes no LLM or external API calls.
"""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import Field, ValidationError

from project_catalog_agent.actions import RecoveryActionExecutor
from project_catalog_agent.catalog.contracts import (
    ContractModel,
    CreateProjectRequest,
    ExtractedRequirement,
    IssueCategory,
    IssueSeverity,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RecoveryActionRequest,
    RecoveryActionResult,
    RecoveryContext,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyCandidate,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
    ValidationIssue,
    ValidationResult,
)
from project_catalog_agent.profile import ProjectProfileBuilder
from project_catalog_agent.taxonomy import JsonTaxonomyRepository

DEFAULT_CASES_PATH = Path("tests/manual/recovery_cases.json")


class ExpectedClarification(ContractModel):
    """Optional detailed clarification expectations."""

    issue_code: str
    field: str
    related_raw_skill: str
    expected_option_skill_ids: list[str] = Field(default_factory=list)
    allow_free_text: bool


class ExpectedRecoveryResult(ContractModel):
    """Observable fields compared for one recovery result."""

    status: str
    changed: bool
    error_code: str | None
    extraction_result_present: bool
    normalization_result_present: bool
    candidate_profile_present: bool
    clarification_request_present: bool
    escalation_present: bool
    clarification: ExpectedClarification | None = None


class ManualRecoveryCase(ContractModel):
    """One controlled recovery action and its expected outcome."""

    test_case_id: str
    description: str
    context_reference: str
    action_request: dict[str, object]
    expected: ExpectedRecoveryResult


class ManualRecoverySuite(ContractModel):
    """Validated wrapper for the supplied cases file."""

    test_cases: list[ManualRecoveryCase]


class ControlledExtractor:
    """Return one complete, validated extraction result."""

    def __init__(self, result: RequirementExtractionResult) -> None:
        self._result = result

    async def extract(
        self, request: CreateProjectRequest
    ) -> RequirementExtractionResult:
        return self._result.model_copy(deep=True)


class ControlledNormalizer:
    """Return one complete, validated normalization result."""

    def __init__(self, result: TaxonomyNormalizationResult) -> None:
        self._result = result

    async def normalize(
        self, extraction: RequirementExtractionResult
    ) -> TaxonomyNormalizationResult:
        return self._result.model_copy(deep=True)


def parse_arguments() -> argparse.Namespace:
    """Parse case-file and optional non-interactive selection arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--case",
        type=int,
        help="case index to run; use 0 to run all cases",
    )
    return parser.parse_args()


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[ManualRecoveryCase]:
    """Load and validate the supplied JSON cases."""
    with path.open("r", encoding="utf-8") as handle:
        payload: object = json.load(handle)
    return ManualRecoverySuite.model_validate(payload).test_cases


def select_cases(
    cases: list[ManualRecoveryCase], case_index: int | None
) -> list[ManualRecoveryCase]:
    """Select all cases for zero or one case by its one-based index."""
    if case_index is not None and not 0 <= case_index <= len(cases):
        msg = f"case index must be between 0 and {len(cases)}"
        raise ValueError(msg)
    if case_index is None:
        print("Select a Step 8 recovery case:")
        print("  0. Run all cases")
        for index, recovery_case in enumerate(cases, start=1):
            print(
                f"  {index}. {recovery_case.test_case_id}: {recovery_case.description}"
            )
        while case_index is None:
            raw_value = input(f"Enter a number (0-{len(cases)}): ").strip()
            if raw_value.isdigit() and 0 <= int(raw_value) <= len(cases):
                case_index = int(raw_value)
            else:
                print("Invalid selection. Please enter one listed number.")
    return cases if case_index == 0 else [cases[case_index - 1]]


def _extraction(
    raw_skill: str,
    *,
    confidence: float = 0.9,
    level: ProficiencyLevel | None = ProficiencyLevel.INTERMEDIATE,
) -> RequirementExtractionResult:
    return RequirementExtractionResult(
        project_summary=f"A controlled project using {raw_skill}.",
        requirements=[
            ExtractedRequirement(
                raw_skill=raw_skill,
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=level,
                confidence=confidence,
                evidence_text=f"Use {raw_skill} to complete the project.",
                decision_basis=f"{raw_skill} is needed for mandatory work.",
            )
        ],
    )


def _resolved(raw_skill: str, skill_id: str, name: str) -> TaxonomyNormalizationResult:
    return TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill=raw_skill,
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id=skill_id,
                canonical_skill=name,
                decision_basis="Controlled canonical mapping.",
            )
        ]
    )


def _unresolved(
    raw_skill: str, *, candidates: bool = False
) -> TaxonomyNormalizationResult:
    return TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill=raw_skill,
                status=(
                    MappingStatus.NEEDS_REVIEW if candidates else MappingStatus.UNMAPPED
                ),
                match_method=MatchMethod.UNRESOLVED,
                candidates=(
                    [
                        TaxonomyCandidate(skill_id="aws", canonical_name="AWS"),
                        TaxonomyCandidate(
                            skill_id="gcp-azure", canonical_name="GCP/Azure"
                        ),
                    ]
                    if candidates
                    else []
                ),
                decision_basis="Controlled unresolved mapping.",
            )
        ],
        unresolved_skills=[raw_skill],
    )


def _scenario_artifacts(
    reference: str,
) -> tuple[
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
    bool,
]:
    """Return current and controlled service outputs for a context name."""
    if reference in {"context_rebuild", "context_rebuild_no_change"}:
        current_extraction = _extraction("Python")
        current_normalization = _resolved("Python", "python", "Python")
        return (
            current_extraction,
            current_normalization,
            current_extraction,
            current_normalization,
            reference == "context_rebuild",
        )
    if reference == "context_low_confidence":
        current_extraction = _extraction("Python", confidence=0.4)
        return (
            current_extraction,
            _resolved("Python", "python", "Python"),
            _extraction("Python", confidence=0.95),
            _resolved("Python", "python", "Python"),
            False,
        )
    if reference == "context_unmapped_resolvable":
        current_extraction = _extraction("FastAPI")
        return (
            current_extraction,
            _unresolved("FastAPI"),
            current_extraction,
            _resolved("FastAPI", "flask-fastapi", "Flask/FastAPI"),
            False,
        )
    if reference == "context_unmapped_unchanged":
        current_extraction = _extraction("Uncatalogued Quantum Framework")
        current_normalization = _unresolved("Uncatalogued Quantum Framework")
        return (
            current_extraction,
            current_normalization,
            current_extraction,
            current_normalization,
            False,
        )
    if reference == "context_needs_review":
        raw_skill = "AWS, Azure, or GCP"
        current_extraction = _extraction(raw_skill)
        return (
            current_extraction,
            _unresolved(raw_skill, candidates=True),
            current_extraction,
            _resolved(raw_skill, "aws", "AWS"),
            False,
        )
    if reference == "context_missing_level":
        current_extraction = _extraction("Python", level=None)
        current_normalization = _resolved("Python", "python", "Python")
        return (
            current_extraction,
            current_normalization,
            current_extraction,
            current_normalization,
            False,
        )
    msg = f"unknown context_reference: {reference}"
    raise ValueError(msg)


def build_runtime(
    recovery_case: ManualRecoveryCase,
    action_request: RecoveryActionRequest,
) -> tuple[RecoveryActionExecutor, RecoveryContext]:
    """Build a real executor around controlled inputs for one supplied case."""
    extracted, normalized, extractor_output, normalizer_output, make_stale = (
        _scenario_artifacts(recovery_case.context_reference)
    )
    request = CreateProjectRequest(
        request_id=action_request.request_id,
        project_name=recovery_case.description,
        project_description=extracted.requirements[0].evidence_text,
    )
    builder = ProjectProfileBuilder()
    profile = builder.build(
        request=request,
        extraction=extracted,
        normalization=normalized,
    )
    if make_stale:
        stale_requirement = profile.requirements[0].model_copy(
            update={"importance": RequirementImportance.PREFERRED},
            deep=True,
        )
        profile = profile.model_copy(update={"requirements": [stale_requirement]})

    permitted_actions = [action_request.action.value]
    if recovery_case.test_case_id == "REC-011":
        permitted_actions = ["lookup_taxonomy"]
    issue_field = action_request.issue_field
    if recovery_case.test_case_id == "REC-012":
        issue_field = "unresolved_requirements[0]"
    issue = ValidationIssue(
        code=action_request.issue_code,
        field=issue_field,
        severity=IssueSeverity.BLOCKING,
        category=IssueCategory.CONFLICT,
        message="Controlled manual recovery issue.",
        resolvable_by=permitted_actions,
    )
    context = RecoveryContext(
        request=request,
        extraction_result=extracted,
        normalization_result=normalized,
        candidate_profile=profile,
        validation_result=ValidationResult(valid=False, issues=[issue]),
    )
    executor = RecoveryActionExecutor(
        extractor=ControlledExtractor(extractor_output),
        normalizer=ControlledNormalizer(normalizer_output),
        profile_builder=builder,
        taxonomy_repository=JsonTaxonomyRepository(),
    )
    return executor, context


def _actual_values(result: RecoveryActionResult) -> dict[str, object]:
    return {
        "status": result.status.value,
        "changed": result.changed,
        "error_code": result.error_code,
        "extraction_result_present": result.extraction_result is not None,
        "normalization_result_present": result.normalization_result is not None,
        "candidate_profile_present": result.candidate_profile is not None,
        "clarification_request_present": result.clarification_request is not None,
        "escalation_present": result.escalation is not None,
    }


def result_matches(
    result: RecoveryActionResult,
    expected: ExpectedRecoveryResult,
) -> bool:
    """Compare all supplied observable expectations."""
    base_matches = _actual_values(result) == expected.model_dump(
        exclude={"clarification"}
    )
    if not base_matches or expected.clarification is None:
        return base_matches
    clarification = result.clarification_request
    if clarification is None:
        return False
    return (
        clarification.issue_code == expected.clarification.issue_code
        and clarification.field == expected.clarification.field
        and clarification.related_raw_skill == expected.clarification.related_raw_skill
        and [
            option.skill_id
            for option in clarification.options
            if option.skill_id is not None
        ]
        == expected.clarification.expected_option_skill_ids
        and clarification.allow_free_text is expected.clarification.allow_free_text
    )


async def run_case(recovery_case: ManualRecoveryCase) -> bool:
    """Run and print one case, including request-boundary failures."""
    print(f"\n--- {recovery_case.test_case_id}: {recovery_case.description} ---")
    try:
        action_request = RecoveryActionRequest.model_validate(
            recovery_case.action_request
        )
    except ValidationError as error:
        passed = (
            recovery_case.expected.status == "failed"
            and recovery_case.expected.changed is False
            and recovery_case.expected.error_code == "INVALID_ACTION_TARGET"
        )
        print("Action request rejected at the typed boundary.")
        print(f"Error: {error.errors(include_input=False, include_url=False)}")
        print("Actual: failed / INVALID_ACTION_TARGET")
        print(f"Result: {'PASS' if passed else 'FAIL'}")
        return passed

    executor, context = build_runtime(recovery_case, action_request)
    result = await executor.execute(action_request=action_request, context=context)
    passed = result_matches(result, recovery_case.expected)
    print(result.model_dump_json(indent=2, exclude_none=True))
    print(f"Expected: {recovery_case.expected.model_dump_json()}")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    return passed


async def async_main() -> int:
    """Run selected cases and return a shell-friendly status code."""
    arguments = parse_arguments()
    selected = select_cases(load_cases(arguments.cases), arguments.case)
    results = [await run_case(recovery_case) for recovery_case in selected]
    passed_count = sum(results)
    print("\nSummary")
    print(f"  Passed: {passed_count}")
    print(f"  Failed: {len(results) - passed_count}")
    print(f"  Total:  {len(results)}")
    return 0 if all(results) else 1


def main() -> int:
    """Run the asynchronous manual harness."""
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
