"""Tests for deterministic catalog next-step selection."""

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from project_catalog_agent.agent import CatalogDecisionPolicy, CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    AgentError,
    CatalogAgentState,
    CatalogDecision,
    CatalogDecisionPolicyConfig,
    CatalogStage,
    CatalogStatus,
    ClarificationRequest,
    CreateProjectRequest,
    DecisionReason,
    DecisionType,
    EscalationRequest,
    ExtractedRequirement,
    IssueCategory,
    IssueSeverity,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryActionResult,
    RecoveryStatus,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
    ValidationIssue,
    ValidationResult,
    create_initial_catalog_state,
)
from project_catalog_agent.errors import InvalidDecisionStateError
from project_catalog_agent.profile import ProjectProfileBuilder


def request() -> CreateProjectRequest:
    return CreateProjectRequest(
        request_id="DEC-001",
        project_name="Decision Test",
        project_description="Python is required.",
    )


def extraction() -> RequirementExtractionResult:
    return RequirementExtractionResult(
        project_summary="A decision-policy test.",
        requirements=[
            ExtractedRequirement(
                raw_skill="Python",
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=ProficiencyLevel.INTERMEDIATE,
                confidence=0.9,
                evidence_text="Python is required.",
                decision_basis="Python is mandatory.",
            )
        ],
    )


def normalization() -> TaxonomyNormalizationResult:
    return TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill="Python",
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id="python",
                canonical_skill="Python",
                decision_basis="Exact match.",
            )
        ]
    )


def pipeline_states() -> tuple[CatalogAgentState, ...]:
    updater = CatalogStateUpdater()
    initial = create_initial_catalog_state(request())
    extracted = updater.apply_extraction(initial, extraction())
    normalized = updater.apply_normalization(extracted, normalization())
    profile = ProjectProfileBuilder().build(
        request=normalized.request,
        extraction=extraction(),
        normalization=normalization(),
    )
    profiled = updater.apply_profile(normalized, profile)
    completed = updater.apply_validation(profiled, ValidationResult(valid=True))
    return initial, extracted, normalized, profiled, completed


def issue(
    code: str,
    field: str,
    actions: Sequence[RecoveryActionName],
    *,
    severity: IssueSeverity = IssueSeverity.BLOCKING,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        field=field,
        severity=severity,
        category=IssueCategory.CONFLICT,
        message=f"Controlled {code} issue.",
        resolvable_by=[action.value for action in actions],
    )


def invalid_state(*issues: ValidationIssue) -> CatalogAgentState:
    return CatalogStateUpdater().apply_validation(
        pipeline_states()[3], ValidationResult(valid=False, issues=list(issues))
    )


def apply_outcome(
    state: CatalogAgentState,
    selected_issue: ValidationIssue,
    action: RecoveryActionName,
    status: RecoveryStatus,
) -> CatalogAgentState:
    request_value = RecoveryActionRequest(
        request_id=state.request.request_id,
        action=action,
        issue_code=selected_issue.code,
        issue_field=selected_issue.field,
    )
    values: dict[str, object] = {
        "request_id": state.request.request_id,
        "action": action,
        "issue_code": selected_issue.code,
        "status": status,
        "changed": False,
        "message": "Controlled prior recovery.",
    }
    if status is RecoveryStatus.FAILED:
        values["error_code"] = "CONTROLLED_FAILURE"
    result = RecoveryActionResult.model_validate(values)
    return CatalogStateUpdater().apply_recovery_result(state, request_value, result)


@pytest.mark.parametrize(
    ("index", "decision_type", "reason"),
    [
        (0, DecisionType.RUN_EXTRACTION, DecisionReason.EXTRACTION_REQUIRED),
        (1, DecisionType.RUN_NORMALIZATION, DecisionReason.NORMALIZATION_REQUIRED),
        (2, DecisionType.BUILD_PROFILE, DecisionReason.PROFILE_BUILD_REQUIRED),
        (3, DecisionType.RUN_VALIDATION, DecisionReason.VALIDATION_REQUIRED),
        (
            4,
            DecisionType.PUBLISH_PROFILE,
            DecisionReason.PROFILE_READY_TO_PUBLISH,
        ),
    ],
)
def test_pipeline_progression(
    index: int, decision_type: DecisionType, reason: DecisionReason
) -> None:
    decision = CatalogDecisionPolicy().decide(pipeline_states()[index])

    assert decision.decision_type is decision_type
    assert decision.reason_code is reason
    assert decision.action_request is None


def test_warning_only_valid_profile_is_ready_to_publish() -> None:
    warning = issue(
        "LOW_EXTRACTION_CONFIDENCE",
        "requirements[0].confidence",
        [RecoveryActionName.REEXTRACT_FIELD],
        severity=IssueSeverity.WARNING,
    )
    state = CatalogStateUpdater().apply_validation(
        pipeline_states()[3], ValidationResult(valid=True, issues=[warning])
    )

    assert (
        CatalogDecisionPolicy().decide(state).decision_type
        is DecisionType.PUBLISH_PROFILE
    )


def test_paused_and_terminal_states_stop_before_pipeline_checks() -> None:
    profiled = pipeline_states()[3]
    clarification = ClarificationRequest(
        clarification_id="clarification-DEC-001",
        request_id="DEC-001",
        issue_code="MISSING_REQUIRED_LEVEL",
        field="requirements[0].required_level",
        question="What level is required?",
    )
    awaiting = CatalogAgentState.model_validate(
        {
            **profiled.model_dump(),
            "status": CatalogStatus.AWAITING_CLARIFICATION,
            "stage": CatalogStage.AWAITING_CLARIFICATION,
            "pending_clarification": clarification,
        }
    )
    escalation = EscalationRequest(
        escalation_id="escalation-DEC-001",
        request_id="DEC-001",
        issue_code="UNKNOWN",
        field="profile",
        reason="Unsafe.",
        context_summary="Controlled case.",
        recommended_review="Review it.",
    )
    escalated = CatalogAgentState.model_validate(
        {
            **profiled.model_dump(),
            "status": CatalogStatus.ESCALATED,
            "stage": CatalogStage.ESCALATED,
            "escalation": escalation,
        }
    )
    permanent = CatalogStateUpdater().add_error(
        create_initial_catalog_state(request()),
        AgentError(
            code="PERMANENT",
            message="Permanent failure.",
            stage=CatalogStage.RECEIVED,
            retryable=False,
        ),
    )

    assert (
        CatalogDecisionPolicy().decide(awaiting).decision_type
        is DecisionType.WAIT_FOR_CLARIFICATION
    )
    assert (
        CatalogDecisionPolicy().decide(escalated).decision_type
        is DecisionType.STOP_ESCALATED
    )
    assert (
        CatalogDecisionPolicy().decide(permanent).decision_type
        is DecisionType.STOP_PERMANENT_FAILURE
    )


def test_issue_priority_ignores_warning_and_preserves_defined_order() -> None:
    warning = issue(
        "LOW_EXTRACTION_CONFIDENCE",
        "requirements[0].confidence",
        [RecoveryActionName.REEXTRACT_FIELD],
        severity=IssueSeverity.WARNING,
    )
    extraction_issue = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements[0].required_level",
        [RecoveryActionName.REEXTRACT_FIELD],
    )
    taxonomy_issue = issue(
        "UNKNOWN_SKILL_ID",
        "requirements[0].skill_id",
        [RecoveryActionName.LOOKUP_TAXONOMY],
    )
    internal_issue = issue(
        "EMPTY_PROVENANCE",
        "requirements[0].provenance",
        [RecoveryActionName.REBUILD_PROFILE],
    )

    decision = CatalogDecisionPolicy().decide(
        invalid_state(warning, extraction_issue, taxonomy_issue, internal_issue)
    )

    assert decision.selected_issue_code == "EMPTY_PROVENANCE"
    assert decision.action_request is not None
    assert decision.action_request.action is RecoveryActionName.REBUILD_PROFILE

    first_taxonomy = CatalogDecisionPolicy().decide(
        invalid_state(extraction_issue, taxonomy_issue)
    )
    assert first_taxonomy.selected_issue_code == "UNKNOWN_SKILL_ID"

    same_priority = CatalogDecisionPolicy().decide(
        invalid_state(
            issue(
                "MISSING_REQUIRED_LEVEL",
                "requirements[0].required_level",
                [RecoveryActionName.REEXTRACT_FIELD],
            ),
            issue(
                "EVIDENCE_NOT_VERBATIM",
                "requirements[0].evidence_text",
                [RecoveryActionName.REEXTRACT_FIELD],
            ),
        )
    )
    assert same_priority.selected_issue_code == "MISSING_REQUIRED_LEVEL"


@pytest.mark.parametrize(
    ("code", "field", "expected_action"),
    [
        (
            "EMPTY_PROVENANCE",
            "requirements[0].provenance",
            RecoveryActionName.REBUILD_PROFILE,
        ),
        (
            "MISSING_REQUIRED_LEVEL",
            "requirements[0].required_level",
            RecoveryActionName.REEXTRACT_FIELD,
        ),
        (
            "UNKNOWN_SKILL_ID",
            "requirements[0].skill_id",
            RecoveryActionName.LOOKUP_TAXONOMY,
        ),
        (
            "NEEDS_REVIEW_REQUIREMENT",
            "unresolved_requirements[0]",
            RecoveryActionName.RECONSIDER_MAPPING,
        ),
    ],
)
def test_preferred_action_selection(
    code: str, field: str, expected_action: RecoveryActionName
) -> None:
    actions = {
        "EMPTY_PROVENANCE": [
            RecoveryActionName.REBUILD_PROFILE,
            RecoveryActionName.ESCALATE,
        ],
        "MISSING_REQUIRED_LEVEL": [
            RecoveryActionName.REEXTRACT_FIELD,
            RecoveryActionName.REQUEST_CLARIFICATION,
        ],
        "UNKNOWN_SKILL_ID": [
            RecoveryActionName.LOOKUP_TAXONOMY,
            RecoveryActionName.ESCALATE,
        ],
        "NEEDS_REVIEW_REQUIREMENT": [
            RecoveryActionName.RECONSIDER_MAPPING,
            RecoveryActionName.REQUEST_CLARIFICATION,
        ],
    }[code]
    decision = CatalogDecisionPolicy().decide(
        invalid_state(issue(code, field, actions))
    )

    assert decision.decision_type is DecisionType.EXECUTE_RECOVERY
    assert decision.reason_code is DecisionReason.AUTOMATIC_RECOVERY_AVAILABLE
    assert decision.action_request is not None
    assert decision.action_request.action is expected_action
    assert decision.action_request.context == {}
    assert decision.selected_issue_code == code
    assert decision.selected_issue_field == field


def test_preferences_are_intersected_with_permissions() -> None:
    selected_issue = issue(
        "UNKNOWN_SKILL_ID",
        "requirements[0].skill_id",
        [RecoveryActionName.REQUEST_CLARIFICATION, RecoveryActionName.ESCALATE],
    )

    decision = CatalogDecisionPolicy().decide(invalid_state(selected_issue))

    assert decision.action_request is not None
    assert decision.action_request.action is RecoveryActionName.REQUEST_CLARIFICATION
    assert decision.reason_code is DecisionReason.CLARIFICATION_REQUIRED


def test_unknown_issue_escalates_without_inventing_action() -> None:
    unknown = issue(
        "FUTURE_UNKNOWN_ISSUE",
        "profile",
        [RecoveryActionName.REEXTRACT_FIELD, RecoveryActionName.ESCALATE],
    )
    decision = CatalogDecisionPolicy().decide(invalid_state(unknown))

    assert decision.action_request is not None
    assert decision.action_request.action is RecoveryActionName.ESCALATE
    assert decision.reason_code is DecisionReason.NO_SAFE_ACTION


def test_unknown_issue_without_escalation_stops_permanently() -> None:
    unknown = issue(
        "FUTURE_UNKNOWN_ISSUE",
        "profile",
        [RecoveryActionName.REEXTRACT_FIELD],
    )

    decision = CatalogDecisionPolicy().decide(invalid_state(unknown))

    assert decision.decision_type is DecisionType.STOP_PERMANENT_FAILURE
    assert decision.reason_code is DecisionReason.NO_SAFE_ACTION


def test_failed_action_retries_below_limit_with_incremented_attempt() -> None:
    selected_issue = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements[0].required_level",
        [RecoveryActionName.REEXTRACT_FIELD, RecoveryActionName.REQUEST_CLARIFICATION],
    )
    state = apply_outcome(
        invalid_state(selected_issue),
        selected_issue,
        RecoveryActionName.REEXTRACT_FIELD,
        RecoveryStatus.FAILED,
    )

    decision = CatalogDecisionPolicy().decide(state)

    assert decision.action_request is not None
    assert decision.action_request.action is RecoveryActionName.REEXTRACT_FIELD
    assert decision.action_request.attempt_number == 2


def test_exhausted_or_disabled_action_advances_to_clarification() -> None:
    selected_issue = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements[0].required_level",
        [RecoveryActionName.REEXTRACT_FIELD, RecoveryActionName.REQUEST_CLARIFICATION],
    )
    disabled = CatalogDecisionPolicy(
        CatalogDecisionPolicyConfig(max_reextraction_attempts=0)
    ).decide(invalid_state(selected_issue))
    state = invalid_state(selected_issue)
    state = apply_outcome(
        state,
        selected_issue,
        RecoveryActionName.REEXTRACT_FIELD,
        RecoveryStatus.FAILED,
    )
    state = apply_outcome(
        state,
        selected_issue,
        RecoveryActionName.REEXTRACT_FIELD,
        RecoveryStatus.FAILED,
    )
    exhausted = CatalogDecisionPolicy().decide(state)

    assert disabled.action_request is not None
    assert disabled.action_request.action is RecoveryActionName.REQUEST_CLARIFICATION
    assert exhausted.action_request is not None
    assert exhausted.action_request.action is RecoveryActionName.REQUEST_CLARIFICATION


def test_total_limit_escalates_or_stops() -> None:
    selected_issue = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements[0].required_level",
        [RecoveryActionName.REEXTRACT_FIELD, RecoveryActionName.ESCALATE],
    )
    state = apply_outcome(
        invalid_state(selected_issue),
        selected_issue,
        RecoveryActionName.REEXTRACT_FIELD,
        RecoveryStatus.FAILED,
    )
    config = CatalogDecisionPolicyConfig(max_total_recovery_attempts=1)
    escalated = CatalogDecisionPolicy(config).decide(state)
    no_escalation = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements[0].required_level",
        [RecoveryActionName.REEXTRACT_FIELD],
    )
    stopped = CatalogDecisionPolicy(
        CatalogDecisionPolicyConfig(max_total_recovery_attempts=0)
    ).decide(invalid_state(no_escalation))

    assert escalated.action_request is not None
    assert escalated.action_request.action is RecoveryActionName.ESCALATE
    assert escalated.reason_code is DecisionReason.RETRY_LIMIT_REACHED
    assert stopped.decision_type is DecisionType.STOP_PERMANENT_FAILURE


@pytest.mark.parametrize(
    ("code", "field", "automatic", "next_action"),
    [
        (
            "UNMAPPED_REQUIREMENT",
            "unresolved_requirements[0]",
            RecoveryActionName.LOOKUP_TAXONOMY,
            RecoveryActionName.REQUEST_CLARIFICATION,
        ),
        (
            "NEEDS_REVIEW_REQUIREMENT",
            "unresolved_requirements[0]",
            RecoveryActionName.RECONSIDER_MAPPING,
            RecoveryActionName.REQUEST_CLARIFICATION,
        ),
        (
            "EMPTY_PROVENANCE",
            "requirements[0].provenance",
            RecoveryActionName.REBUILD_PROFILE,
            RecoveryActionName.ESCALATE,
        ),
    ],
)
def test_no_change_is_not_repeated(
    code: str,
    field: str,
    automatic: RecoveryActionName,
    next_action: RecoveryActionName,
) -> None:
    selected_issue = issue(
        code,
        field,
        [
            automatic,
            RecoveryActionName.REQUEST_CLARIFICATION,
            RecoveryActionName.ESCALATE,
        ],
    )
    state = apply_outcome(
        invalid_state(selected_issue),
        selected_issue,
        automatic,
        RecoveryStatus.NO_CHANGE,
    )

    decision = CatalogDecisionPolicy().decide(state)

    assert decision.action_request is not None
    assert decision.action_request.action is next_action


def test_clarification_is_not_requested_twice() -> None:
    selected_issue = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements[0].required_level",
        [RecoveryActionName.REQUEST_CLARIFICATION, RecoveryActionName.ESCALATE],
    )
    state = invalid_state(selected_issue)
    request_value = RecoveryActionRequest(
        request_id="DEC-001",
        action=RecoveryActionName.REQUEST_CLARIFICATION,
        issue_code=selected_issue.code,
        issue_field=selected_issue.field,
    )
    awaiting = RecoveryActionResult(
        request_id="DEC-001",
        action=RecoveryActionName.REQUEST_CLARIFICATION,
        issue_code=selected_issue.code,
        status=RecoveryStatus.AWAITING_INPUT,
        changed=False,
        clarification_request=ClarificationRequest(
            clarification_id="clarification-DEC-001",
            request_id="DEC-001",
            issue_code=selected_issue.code,
            field=selected_issue.field,
            question="What level is required?",
        ),
        message="Clarification prepared.",
    )
    awaiting_state = CatalogStateUpdater().apply_recovery_result(
        state, request_value, awaiting
    )

    assert (
        CatalogDecisionPolicy().decide(awaiting_state).decision_type
        is DecisionType.WAIT_FOR_CLARIFICATION
    )


@pytest.mark.parametrize(
    ("field", "requirement", "provenance", "unresolved"),
    [
        ("requirements[2].required_level", 2, None, None),
        ("requirements[1].provenance[3].evidence_text", 1, 3, None),
        ("unresolved_requirements[4].raw_skill", None, None, 4),
    ],
)
def test_recovery_request_parses_known_target_indexes(
    field: str,
    requirement: int | None,
    provenance: int | None,
    unresolved: int | None,
) -> None:
    selected_issue = issue(
        "MISSING_REQUIRED_LEVEL",
        field,
        [RecoveryActionName.REEXTRACT_FIELD],
    )
    decision = CatalogDecisionPolicy().decide(invalid_state(selected_issue))
    assert decision.action_request is not None
    assert decision.action_request.request_id == "DEC-001"
    assert decision.action_request.target_requirement_index == requirement
    assert decision.action_request.target_provenance_index == provenance
    assert decision.action_request.target_unresolved_index == unresolved


def test_malformed_target_skips_unsafe_action_and_escalates() -> None:
    selected_issue = issue(
        "MISSING_REQUIRED_LEVEL",
        "requirements from user text",
        [RecoveryActionName.REEXTRACT_FIELD, RecoveryActionName.ESCALATE],
    )

    decision = CatalogDecisionPolicy().decide(invalid_state(selected_issue))

    assert decision.action_request is not None
    assert decision.action_request.action is RecoveryActionName.ESCALATE


def test_invalid_false_validation_without_blocking_issue_is_rejected() -> None:
    warning = issue(
        "LOW_EXTRACTION_CONFIDENCE",
        "requirements[0].confidence",
        [RecoveryActionName.REEXTRACT_FIELD],
        severity=IssueSeverity.WARNING,
    )
    state = CatalogStateUpdater().apply_validation(
        pipeline_states()[3], ValidationResult(valid=False, issues=[warning])
    )

    with pytest.raises(InvalidDecisionStateError):
        CatalogDecisionPolicy().decide(state)


def test_retry_accounting_mismatch_is_rejected() -> None:
    state = invalid_state(
        issue(
            "MISSING_REQUIRED_LEVEL",
            "requirements[0].required_level",
            [RecoveryActionName.REEXTRACT_FIELD],
        )
    )
    corrupted = CatalogAgentState.model_validate(
        {
            **state.model_dump(),
            "retry_counts": {RecoveryActionName.REEXTRACT_FIELD: 1},
        }
    )

    with pytest.raises(InvalidDecisionStateError):
        CatalogDecisionPolicy().decide(corrupted)


def test_policy_is_pure_deterministic_and_does_not_increment_counts() -> None:
    state = invalid_state(
        issue(
            "MISSING_REQUIRED_LEVEL",
            "requirements[0].required_level",
            [RecoveryActionName.REEXTRACT_FIELD],
        )
    )
    before = state.model_dump(mode="json")
    policy = CatalogDecisionPolicy()

    first = policy.decide(state)
    second = policy.decide(state)

    assert first == second
    assert state.model_dump(mode="json") == before
    assert state.retry_counts == {}
    assert first.model_dump_json() == second.model_dump_json()


def test_decision_and_config_contracts_reject_invalid_shapes() -> None:
    with pytest.raises(ValidationError):
        CatalogDecision(
            decision_type=DecisionType.EXECUTE_RECOVERY,
            reason_code=DecisionReason.AUTOMATIC_RECOVERY_AVAILABLE,
            message="Missing action.",
        )
    with pytest.raises(ValidationError):
        CatalogDecision(
            decision_type=DecisionType.COMPLETE,
            reason_code=DecisionReason.PROFILE_VALID,
            message="Unexpected action.",
            action_request=RecoveryActionRequest(
                request_id="DEC-001",
                action=RecoveryActionName.REBUILD_PROFILE,
                issue_code="ISSUE",
                issue_field="requirements",
            ),
        )
    with pytest.raises(ValidationError):
        CatalogDecisionPolicyConfig(max_total_recovery_attempts=-1)
