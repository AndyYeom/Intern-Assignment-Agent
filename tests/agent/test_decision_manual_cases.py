"""JSON-driven Step 10 manual decision scenarios."""

import json
from pathlib import Path
from typing import TypedDict

from project_catalog_agent.agent import CatalogDecisionPolicy, CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ClarificationRequest,
    EscalationRequest,
    IssueSeverity,
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryActionResult,
    RecoveryStatus,
    ValidationResult,
)
from tests.agent.test_decision import (
    apply_outcome,
    invalid_state,
    issue,
    pipeline_states,
)

CASES_PATH = Path("tests/manual/decision_cases.json")


class DecisionCase(TypedDict, total=False):
    case_id: str
    scenario: str
    expected_type: str
    expected_reason: str
    expected_action: str
    expected_attempt: int
    expected_issue: str


def load_cases() -> list[DecisionCase]:
    with CASES_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload["test_cases"])


def _recovery_state(code: str, action: RecoveryActionName) -> CatalogAgentState:
    field = (
        "unresolved_requirements[0]"
        if code == "NEEDS_REVIEW_REQUIREMENT"
        else "requirements[0].required_level"
    )
    selected = issue(
        code,
        field,
        [action, RecoveryActionName.REQUEST_CLARIFICATION, RecoveryActionName.ESCALATE],
    )
    return apply_outcome(
        invalid_state(selected), selected, action, RecoveryStatus.NO_CHANGE
    )


def scenario_state(name: str) -> CatalogAgentState:
    states = pipeline_states()
    if name in {"initial", "extracted", "normalized", "profiled", "valid"}:
        return states[
            {"initial": 0, "extracted": 1, "normalized": 2, "profiled": 3, "valid": 4}[
                name
            ]
        ]
    missing = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements[0].required_level",
        [
            RecoveryActionName.REEXTRACT_FIELD,
            RecoveryActionName.REQUEST_CLARIFICATION,
            RecoveryActionName.ESCALATE,
        ],
    )
    if name == "missing_level":
        return invalid_state(missing)
    if name == "reextract_no_change":
        return _recovery_state(
            "MISSING_REQUIRED_LEVEL", RecoveryActionName.REEXTRACT_FIELD
        )
    if name == "needs_review":
        return invalid_state(
            issue(
                "NEEDS_REVIEW_REQUIREMENT",
                "unresolved_requirements[0]",
                [
                    RecoveryActionName.RECONSIDER_MAPPING,
                    RecoveryActionName.REQUEST_CLARIFICATION,
                    RecoveryActionName.ESCALATE,
                ],
            )
        )
    if name == "reconsider_no_change":
        return _recovery_state(
            "NEEDS_REVIEW_REQUIREMENT", RecoveryActionName.RECONSIDER_MAPPING
        )
    if name == "clarification_pending":
        return _pending_state(invalid_state(missing), missing)
    if name == "recovery_exhausted":
        state = invalid_state(missing)
        state = apply_outcome(
            state, missing, RecoveryActionName.REEXTRACT_FIELD, RecoveryStatus.FAILED
        )
        state = apply_outcome(
            state, missing, RecoveryActionName.REEXTRACT_FIELD, RecoveryStatus.FAILED
        )
        pending = _pending_state(state, missing)
        return CatalogAgentState.model_validate(
            {
                **pending.model_dump(),
                "status": CatalogStatus.PROCESSING,
                "stage": CatalogStage.VALIDATED,
                "pending_clarification": None,
            }
        )
    if name == "already_escalated":
        return _escalated_state(invalid_state(missing), missing)
    if name == "valid_with_warning":
        warning = issue(
            "LOW_EXTRACTION_CONFIDENCE",
            "requirements[0].confidence",
            [RecoveryActionName.REEXTRACT_FIELD],
            severity=IssueSeverity.WARNING,
        )
        return CatalogStateUpdater().apply_validation(
            states[3], ValidationResult(valid=True, issues=[warning])
        )
    if name == "warning_and_blocking":
        warning = issue(
            "LOW_EXTRACTION_CONFIDENCE",
            "requirements[0].confidence",
            [RecoveryActionName.REEXTRACT_FIELD],
            severity=IssueSeverity.WARNING,
        )
        return invalid_state(warning, missing)
    if name == "preferred_not_permitted":
        return invalid_state(
            issue(
                "MISSING_REQUIRED_LEVEL",
                "requirements[0].required_level",
                [RecoveryActionName.REQUEST_CLARIFICATION],
            )
        )
    raise ValueError(f"unknown scenario: {name}")


def _pending_state(state: CatalogAgentState, selected_issue) -> CatalogAgentState:  # type: ignore[no-untyped-def]
    action = RecoveryActionName.REQUEST_CLARIFICATION
    return CatalogStateUpdater().apply_recovery_result(
        state,
        RecoveryActionRequest(
            request_id="DEC-001",
            action=action,
            issue_code=selected_issue.code,
            issue_field=selected_issue.field,
        ),
        RecoveryActionResult(
            request_id="DEC-001",
            action=action,
            issue_code=selected_issue.code,
            status=RecoveryStatus.AWAITING_INPUT,
            changed=False,
            clarification_request=ClarificationRequest(
                clarification_id="clarification-DEC-001",
                request_id="DEC-001",
                issue_code=selected_issue.code,
                field=selected_issue.field,
                question="What value is required?",
            ),
            message="Clarification prepared.",
        ),
    )


def _escalated_state(state: CatalogAgentState, selected_issue) -> CatalogAgentState:  # type: ignore[no-untyped-def]
    action = RecoveryActionName.ESCALATE
    return CatalogStateUpdater().apply_recovery_result(
        state,
        RecoveryActionRequest(
            request_id="DEC-001",
            action=action,
            issue_code=selected_issue.code,
            issue_field=selected_issue.field,
        ),
        RecoveryActionResult(
            request_id="DEC-001",
            action=action,
            issue_code=selected_issue.code,
            status=RecoveryStatus.ESCALATED,
            changed=False,
            escalation=EscalationRequest(
                escalation_id="escalation-DEC-001",
                request_id="DEC-001",
                issue_code=selected_issue.code,
                field=selected_issue.field,
                reason="Recovery exhausted.",
                context_summary="Controlled decision case.",
                recommended_review="Review the issue.",
            ),
            message="Escalation prepared.",
        ),
    )


def test_all_json_decision_cases_match() -> None:
    cases = load_cases()
    assert len(cases) == 15
    for case in cases:
        decision = CatalogDecisionPolicy().decide(scenario_state(case["scenario"]))
        assert decision.decision_type.value == case["expected_type"], case["case_id"]
        if "expected_reason" in case:
            assert decision.reason_code.value == case["expected_reason"], case[
                "case_id"
            ]
        if "expected_action" in case:
            assert decision.action_request is not None, case["case_id"]
            assert decision.action_request.action.value == case["expected_action"], (
                case["case_id"]
            )
        if "expected_attempt" in case:
            assert decision.action_request is not None
            assert decision.action_request.attempt_number == case["expected_attempt"]
        if "expected_issue" in case:
            assert decision.selected_issue_code == case["expected_issue"]
