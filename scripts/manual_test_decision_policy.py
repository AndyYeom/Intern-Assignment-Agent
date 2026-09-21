"""Run one or all supplied Step 10 decision-policy cases."""

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from project_catalog_agent.agent import CatalogDecisionPolicy, CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    AgentError,
    CatalogAgentState,
    CatalogDecisionPolicyConfig,
    CatalogStage,
    RecoveryActionName,
    RecoveryStatus,
)

DEFAULT_CASES_PATH = Path("tests/manual/decision_policy_cases.json")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_decision_helpers = importlib.import_module("tests.agent.test_decision")
_manual_helpers = importlib.import_module("tests.agent.test_decision_manual_cases")
apply_outcome = _decision_helpers.apply_outcome
invalid_state = _decision_helpers.invalid_state
issue = _decision_helpers.issue
scenario_state = _manual_helpers.scenario_state


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case", type=int, help="case index; use 0 for all")
    return parser.parse_args()


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload: object = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("test_cases"), list):
        raise ValueError("manual decision file must contain test_cases")
    return payload["test_cases"]


def select_cases(
    cases: list[dict[str, Any]], index: int | None
) -> list[dict[str, Any]]:
    if index is not None and not 0 <= index <= len(cases):
        raise ValueError(f"case index must be between 0 and {len(cases)}")
    if index is None:
        print("Select a Step 10 decision case:")
        print("  0. Run all cases")
        for number, case in enumerate(cases, 1):
            print(f"  {number}. {case['test_case_id']}: {case['description']}")
        while index is None:
            raw = input(f"Enter a number (0-{len(cases)}): ").strip()
            if raw.isdigit() and 0 <= int(raw) <= len(cases):
                index = int(raw)
            else:
                print("Invalid selection. Please enter one listed number.")
    return cases if index == 0 else [cases[index - 1]]


def _base_state(reference: str) -> CatalogAgentState:
    aliases = {
        "state_received": "initial",
        "state_extracted": "extracted",
        "state_normalized": "normalized",
        "state_profile_built": "profiled",
        "state_validated_valid": "valid",
        "state_valid_with_warning": "valid_with_warning",
        "state_missing_required_level": "missing_level",
        "state_missing_level_after_no_change": "reextract_no_change",
        "state_needs_review": "needs_review",
        "state_needs_review_after_no_change": "reconsider_no_change",
        "state_awaiting_clarification": "clarification_pending",
        "state_escalated": "already_escalated",
        "state_warning_and_blocking_issue": "warning_and_blocking",
        "state_missing_level_clarification_only": "preferred_not_permitted",
    }
    if reference in aliases:
        return scenario_state(aliases[reference])
    actions = [RecoveryActionName.REBUILD_PROFILE, RecoveryActionName.ESCALATE]
    if reference in {
        "state_provenance_importance_conflict",
        "state_rebuild_after_no_change",
    }:
        selected = issue(
            "PROVENANCE_IMPORTANCE_CONFLICT", "requirements[0].importance", actions
        )
        state = invalid_state(selected)
        return (
            apply_outcome(state, selected, actions[0], RecoveryStatus.NO_CHANGE)
            if reference.endswith("no_change")
            else state
        )
    if reference in {"state_unmapped_requirement", "state_unmapped_after_no_change"}:
        selected = issue(
            "UNMAPPED_REQUIREMENT",
            "unresolved_requirements[0]",
            [RecoveryActionName.LOOKUP_TAXONOMY, RecoveryActionName.ESCALATE],
        )
        state = invalid_state(selected)
        return (
            apply_outcome(
                state,
                selected,
                RecoveryActionName.LOOKUP_TAXONOMY,
                RecoveryStatus.NO_CHANGE,
            )
            if reference.endswith("no_change")
            else state
        )
    if reference == "state_permanent_failure":
        return CatalogStateUpdater().add_error(
            scenario_state("initial"),
            AgentError(
                code="PERMANENT",
                message="Permanent failure.",
                stage=CatalogStage.RECEIVED,
                retryable=False,
            ),
        )
    if reference == "state_multiple_blocking_issues":
        return invalid_state(
            issue(
                "UNMAPPED_REQUIREMENT",
                "unresolved_requirements[0]",
                [RecoveryActionName.LOOKUP_TAXONOMY],
            ),
            issue(
                "PROVENANCE_LEVEL_CONFLICT", "requirements[0].required_level", actions
            ),
        )
    if reference == "state_unknown_blocking_issue_without_escalation":
        return invalid_state(
            issue(
                "UNKNOWN_TEST_ISSUE",
                "requirements[0]",
                [RecoveryActionName.REEXTRACT_FIELD],
            )
        )
    if reference == "state_provenance_evidence_conflict":
        return invalid_state(
            issue(
                "PROVENANCE_EVIDENCE_NOT_VERBATIM",
                "requirements[1].provenance[2].evidence_text",
                [RecoveryActionName.REEXTRACT_FIELD],
            )
        )
    if reference == "state_reextraction_failed_once":
        selected = issue(
            "MISSING_REQUIRED_LEVEL",
            "requirements[0].required_level",
            [RecoveryActionName.REEXTRACT_FIELD, RecoveryActionName.ESCALATE],
        )
        return apply_outcome(
            invalid_state(selected),
            selected,
            RecoveryActionName.REEXTRACT_FIELD,
            RecoveryStatus.FAILED,
        )
    if reference == "state_total_retry_limit_reached":
        selected = issue(
            "MISSING_REQUIRED_LEVEL",
            "requirements[0].required_level",
            [RecoveryActionName.REEXTRACT_FIELD, RecoveryActionName.ESCALATE],
        )
        state = invalid_state(selected)
        for number in range(5):
            extra = issue(
                f"HISTORY_{number}",
                f"requirements[{number}]",
                [RecoveryActionName.REBUILD_PROFILE],
            )
            state = apply_outcome(
                state, extra, RecoveryActionName.REBUILD_PROFILE, RecoveryStatus.FAILED
            )
        return state
    raise ValueError(f"unknown state_reference: {reference}")


def _replace_id(value: Any, request_id: str) -> Any:
    if isinstance(value, str):
        return request_id if value == "DEC-001" else value
    if isinstance(value, list):
        return [_replace_id(item, request_id) for item in value]
    if isinstance(value, dict):
        return {key: _replace_id(item, request_id) for key, item in value.items()}
    return value


def state_for_case(case: dict[str, Any]) -> CatalogAgentState:
    state = _base_state(case["state_reference"])
    return CatalogAgentState.model_validate(
        _replace_id(state.model_dump(), case["test_case_id"])
    )


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], val)
            for key, val in expected.items()
        )
    return actual == expected


def run_case(case: dict[str, Any]) -> bool:
    state = state_for_case(case)
    before = state.model_dump(mode="json")
    policy = CatalogDecisionPolicy(
        CatalogDecisionPolicyConfig.model_validate(case.get("policy_config", {}))
    )
    first = policy.decide(state)
    actual = first.model_dump(mode="json")
    actual["action_request_present"] = first.action_request is not None
    if case.get("operation") == "decide_twice_and_compare":
        second = policy.decide(state)
        actual = {
            "state_unchanged": state.model_dump(mode="json") == before,
            "first_decision_equals_second_decision": first == second,
            "retry_counts_unchanged": state.retry_counts
            == CatalogAgentState.model_validate(before).retry_counts,
            "recovery_history_unchanged": state.recovery_history
            == CatalogAgentState.model_validate(before).recovery_history,
        }
    passed = _contains(actual, case["expected"])
    print(f"\n--- {case['test_case_id']}: {case['description']} ---")
    print(json.dumps(actual, indent=2))
    print(f"Expected: {json.dumps(case['expected'])}")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> int:
    args = parse_arguments()
    results = [
        run_case(case) for case in select_cases(load_cases(args.cases), args.case)
    ]
    print(
        f"\nSummary\n  Passed: {sum(results)}\n  Failed: {len(results) - sum(results)}\n  Total:  {len(results)}"
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
