"""Run one or all supplied Step 9 catalog-state cases.

Enter 0 to run every case or select a one-based case index. Referenced states
are built automatically, and no LLM or external API is called.
"""

import argparse
import json
from pathlib import Path

from pydantic import Field, JsonValue

from project_catalog_agent.agent import CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    ContractModel,
    CreateProjectRequest,
    ProjectProfile,
    RecoveryActionRequest,
    RecoveryActionResult,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
    ValidationResult,
    create_initial_catalog_state,
)
from project_catalog_agent.errors import InvalidStateTransitionError

DEFAULT_CASES_PATH = Path("tests/manual/catalog_state_cases.json")


class ManualStateCase(ContractModel):
    """One supplied operation and expected observable state fields."""

    test_case_id: str
    description: str
    operation: str
    input: dict[str, JsonValue] = Field(default_factory=dict)
    expected: dict[str, JsonValue]
    initial_state_reference: str | None = None


class ManualStateSuite(ContractModel):
    """Validated wrapper for the supplied state cases."""

    test_cases: list[ManualStateCase]


def parse_arguments() -> argparse.Namespace:
    """Parse case-file and optional non-interactive selection arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--case", type=int, help="case index to run; use 0 to run all cases"
    )
    return parser.parse_args()


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[ManualStateCase]:
    """Load and validate the supplied JSON cases."""
    with path.open("r", encoding="utf-8") as handle:
        payload: object = json.load(handle)
    return ManualStateSuite.model_validate(payload).test_cases


def select_cases(
    cases: list[ManualStateCase], case_index: int | None
) -> list[ManualStateCase]:
    """Select all cases for zero or one case by its one-based index."""
    if case_index is not None and not 0 <= case_index <= len(cases):
        msg = f"case index must be between 0 and {len(cases)}"
        raise ValueError(msg)
    if case_index is None:
        print("Select a Step 9 catalog-state case:")
        print("  0. Run all cases")
        for index, state_case in enumerate(cases, start=1):
            print(f"  {index}. {state_case.test_case_id}: {state_case.description}")
        while case_index is None:
            raw_value = input(f"Enter a number (0-{len(cases)}): ").strip()
            if raw_value.isdigit() and 0 <= int(raw_value) <= len(cases):
                case_index = int(raw_value)
            else:
                print("Invalid selection. Please enter one listed number.")
    return cases if case_index == 0 else [cases[case_index - 1]]


def _input(case: ManualStateCase, key: str) -> JsonValue:
    try:
        return case.input[key]
    except KeyError as error:
        msg = f"{case.test_case_id} is missing input {key!r}"
        raise ValueError(msg) from error


def _referenced_state(
    case: ManualStateCase,
    states: dict[str, CatalogAgentState],
) -> CatalogAgentState:
    reference = case.initial_state_reference
    if reference is None:
        msg = f"{case.test_case_id} requires initial_state_reference"
        raise ValueError(msg)
    case_id = reference.removesuffix(".result")
    try:
        return states[case_id]
    except KeyError as error:
        msg = f"state reference {reference!r} is unavailable"
        raise ValueError(msg) from error


def _request(payload: JsonValue) -> CreateProjectRequest:
    if not isinstance(payload, dict):
        raise ValueError("request input must be an object")
    return CreateProjectRequest(
        request_id=str(payload["request_id"]),
        project_name=str(payload["submitted_project_name"]),
        project_description=str(payload["submitted_project_description"]),
    )


def _observations(
    state: CatalogAgentState,
    previous: CatalogAgentState | None = None,
) -> dict[str, JsonValue]:
    validation = state.validation_result
    latest_history = (
        state.recovery_history[-1].model_dump(mode="json")
        if state.recovery_history
        else None
    )
    latest_error = state.errors[-1].model_dump(mode="json") if state.errors else None
    observations: dict[str, JsonValue] = {
        "status": state.status.value,
        "stage": state.stage.value,
        "state_version": state.state_version,
        "extraction_result_present": state.extraction_result is not None,
        "normalization_result_present": state.normalization_result is not None,
        "candidate_profile_present": state.candidate_profile is not None,
        "validation_result_present": validation is not None,
        "pending_clarification_present": state.pending_clarification is not None,
        "escalation_present": state.escalation is not None,
        "recovery_history_length": len(state.recovery_history),
        "retry_counts": {
            action.value: count for action, count in state.retry_counts.items()
        },
        "errors_length": len(state.errors),
    }
    if validation is not None:
        observations["validation_valid"] = validation.valid
    if latest_history is not None:
        observations["latest_history"] = latest_history
    if latest_error is not None:
        observations["latest_error"] = latest_error
    if previous is not None:
        observations["existing_artifacts_preserved"] = all(
            getattr(state, name) == getattr(previous, name)
            for name in (
                "extraction_result",
                "normalization_result",
                "candidate_profile",
                "validation_result",
            )
        )
    return observations


def _contains(actual: JsonValue, expected: JsonValue) -> bool:
    """Return whether actual recursively contains every expected value."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _contains(actual_value, expected_value)
                for actual_value, expected_value in zip(actual, expected, strict=True)
            )
        )
    return actual == expected


def execute_case(
    case: ManualStateCase,
    states: dict[str, CatalogAgentState],
    updater: CatalogStateUpdater,
) -> tuple[bool, CatalogAgentState | None, dict[str, JsonValue]]:
    """Execute one operation and compare the expected observable subset."""
    previous: CatalogAgentState | None = None
    try:
        if case.operation == "create_initial_catalog_state":
            state = create_initial_catalog_state(_request(_input(case, "request")))
        else:
            previous = _referenced_state(case, states)
            before = previous.model_dump(mode="json")
            if case.operation == "apply_extraction":
                state = updater.apply_extraction(
                    previous,
                    RequirementExtractionResult.model_validate(
                        _input(case, "extraction_result")
                    ),
                )
            elif case.operation == "apply_normalization":
                state = updater.apply_normalization(
                    previous,
                    TaxonomyNormalizationResult.model_validate(
                        _input(case, "normalization_result")
                    ),
                )
            elif case.operation == "apply_profile":
                state = updater.apply_profile(
                    previous,
                    ProjectProfile.model_validate(_input(case, "candidate_profile")),
                )
            elif case.operation == "apply_validation":
                state = updater.apply_validation(
                    previous,
                    ValidationResult.model_validate(_input(case, "validation_result")),
                )
            elif case.operation == "apply_recovery_result":
                state = updater.apply_recovery_result(
                    previous,
                    RecoveryActionRequest.model_validate(
                        _input(case, "action_request")
                    ),
                    RecoveryActionResult.model_validate(
                        _input(case, "recovery_result")
                    ),
                )
            elif case.operation == "json_round_trip":
                state = CatalogAgentState.model_validate_json(
                    previous.model_dump_json()
                )
                actual = _observations(state, previous)
                actual["restored_state_equals_original"] = state == previous
                return _contains(actual, case.expected), state, actual
            else:
                raise ValueError(f"unsupported operation: {case.operation}")
            if previous.model_dump(mode="json") != before:
                raise AssertionError("operation mutated its input state")
    except InvalidStateTransitionError as error:
        if previous is None:
            raise
        actual = {
            "exception": type(error).__name__,
            "original_state_unchanged": previous.model_dump(mode="json") == before,
            "original_state_version": previous.state_version,
        }
        return _contains(actual, case.expected), None, actual

    actual = _observations(state, previous)
    return _contains(actual, case.expected), state, actual


def evaluate_cases(
    cases: list[ManualStateCase],
) -> list[tuple[ManualStateCase, bool, dict[str, JsonValue]]]:
    """Resolve dependencies in source order and retain selected reports."""
    updater = CatalogStateUpdater()
    states: dict[str, CatalogAgentState] = {}
    evaluations: list[tuple[ManualStateCase, bool, dict[str, JsonValue]]] = []
    for case in cases:
        passed, state, actual = execute_case(case, states, updater)
        if state is not None:
            states[case.test_case_id] = state
        evaluations.append((case, passed, actual))
    return evaluations


def run_selected(
    all_cases: list[ManualStateCase],
    selected: list[ManualStateCase],
) -> list[bool]:
    """Build all dependencies, then print only selected case reports."""
    selected_ids = {case.test_case_id for case in selected}
    results: list[bool] = []
    for case, passed, actual in evaluate_cases(all_cases):
        if case.test_case_id not in selected_ids:
            continue
        print(f"\n--- {case.test_case_id}: {case.description} ---")
        print(json.dumps(actual, indent=2, ensure_ascii=False))
        print(f"Expected: {json.dumps(case.expected, ensure_ascii=False)}")
        print(f"Result: {'PASS' if passed else 'FAIL'}")
        results.append(passed)
    return results


def main() -> int:
    """Run selected cases and return a shell-friendly status code."""
    arguments = parse_arguments()
    all_cases = load_cases(arguments.cases)
    selected = select_cases(all_cases, arguments.case)
    results = run_selected(all_cases, selected)
    passed_count = sum(results)
    print("\nSummary")
    print(f"  Passed: {passed_count}")
    print(f"  Failed: {len(results) - passed_count}")
    print(f"  Total:  {len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
