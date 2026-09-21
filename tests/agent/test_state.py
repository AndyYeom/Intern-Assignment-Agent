"""Tests for unified catalog state and deterministic transitions."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from project_catalog_agent.agent import CatalogStateUpdater, get_retry_count
from project_catalog_agent.catalog.contracts import (
    AgentError,
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ClarificationRequest,
    CreateProjectRequest,
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
from project_catalog_agent.errors import InvalidStateTransitionError
from project_catalog_agent.profile import ProjectProfileBuilder


def request(request_id: str = "STATE-001") -> CreateProjectRequest:
    """Build one controlled catalog request."""
    return CreateProjectRequest(
        request_id=request_id,
        project_name="State Test",
        project_description="Python is required.",
    )


def extraction(summary: str = "A Python project.") -> RequirementExtractionResult:
    """Build a complete extraction result."""
    return RequirementExtractionResult(
        project_summary=summary,
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
    """Build a complete deterministic normalization result."""
    return TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill="Python",
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id="python",
                canonical_skill="Python",
                decision_basis="Exact canonical match.",
            )
        ]
    )


def invalid_validation() -> ValidationResult:
    """Build one blocking validation result."""
    return ValidationResult(
        valid=False,
        issues=[
            ValidationIssue(
                code="CONTROLLED_ISSUE",
                field="requirements[0]",
                severity=IssueSeverity.BLOCKING,
                category=IssueCategory.CONFLICT,
                message="Controlled blocking issue.",
                resolvable_by=["rebuild_profile", "request_clarification"],
            )
        ],
    )


def pipeline_state(*, valid: bool = False) -> CatalogAgentState:
    """Build state through all pipeline transitions."""
    updater = CatalogStateUpdater()
    initial = create_initial_catalog_state(request())
    extracted = updater.apply_extraction(initial, extraction())
    normalized = updater.apply_normalization(extracted, normalization())
    profile = ProjectProfileBuilder().build(
        request=normalized.request,
        extraction=normalized.extraction_result,  # type: ignore[arg-type]
        normalization=normalized.normalization_result,  # type: ignore[arg-type]
    )
    profiled = updater.apply_profile(normalized, profile)
    result = ValidationResult(valid=True) if valid else invalid_validation()
    return updater.apply_validation(profiled, result)


def action_request(
    action: RecoveryActionName = RecoveryActionName.REBUILD_PROFILE,
) -> RecoveryActionRequest:
    """Build a recovery request bound to the controlled state."""
    return RecoveryActionRequest(
        request_id="STATE-001",
        action=action,
        issue_code="CONTROLLED_ISSUE",
        issue_field="requirements[0]",
    )


def result(
    action: RecoveryActionName,
    status: RecoveryStatus,
    **updates: object,
) -> RecoveryActionResult:
    """Build a recovery result with the required base identity."""
    values: dict[str, object] = {
        "request_id": "STATE-001",
        "action": action,
        "issue_code": "CONTROLLED_ISSUE",
        "status": status,
        "changed": status is RecoveryStatus.SUCCEEDED,
        "message": "Controlled recovery result.",
    }
    values.update(updates)
    return RecoveryActionResult.model_validate(values)


def clarification() -> ClarificationRequest:
    """Build deterministic clarification data."""
    return ClarificationRequest(
        clarification_id="clarification-STATE-001",
        request_id="STATE-001",
        issue_code="CONTROLLED_ISSUE",
        field="requirements[0]",
        question="Which value is correct?",
    )


def escalation() -> EscalationRequest:
    """Build deterministic escalation data."""
    return EscalationRequest(
        escalation_id="escalation-STATE-001",
        request_id="STATE-001",
        issue_code="CONTROLLED_ISSUE",
        field="requirements[0]",
        reason="Automatic recovery is unsafe.",
        context_summary="The controlled issue blocks processing.",
        recommended_review="Review the source evidence.",
    )


def test_initial_state_has_independent_defaults_and_does_not_mutate_request() -> None:
    source_request = request()
    first = create_initial_catalog_state(source_request)
    second = create_initial_catalog_state(request("STATE-002"))

    assert first.request == source_request
    assert first.request is not source_request
    assert first.status is CatalogStatus.RECEIVED
    assert first.stage is CatalogStage.RECEIVED
    assert first.state_version == 1
    assert first.extraction_result is None
    assert first.normalization_result is None
    assert first.candidate_profile is None
    assert first.validation_result is None
    assert first.pending_clarification is None
    assert first.escalation is None
    assert first.recovery_history == []
    assert first.clarification_history == []
    assert first.escalation_review_history == []
    assert first.retry_counts == {}
    assert first.errors == []
    assert first.recovery_history is not second.recovery_history
    assert first.clarification_history is not second.clarification_history
    assert first.escalation_review_history is not second.escalation_review_history
    assert first.errors is not second.errors
    assert first.retry_counts is not second.retry_counts


def test_pipeline_transitions_increment_once_and_apply_expected_stages() -> None:
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

    assert [
        (item.status, item.stage, item.state_version)
        for item in [initial, extracted, normalized, profiled, completed]
    ] == [
        (CatalogStatus.RECEIVED, CatalogStage.RECEIVED, 1),
        (CatalogStatus.PROCESSING, CatalogStage.EXTRACTED, 2),
        (CatalogStatus.PROCESSING, CatalogStage.NORMALIZED, 3),
        (CatalogStatus.PROCESSING, CatalogStage.PROFILE_BUILT, 4),
        (CatalogStatus.PROCESSING, CatalogStage.VALIDATED, 5),
    ]


def test_explicit_equal_extraction_still_increments_and_clears_downstream() -> None:
    updater = CatalogStateUpdater()
    state = pipeline_state()
    original_dump = state.model_dump(mode="json")

    updated = updater.apply_extraction(state, state.extraction_result)  # type: ignore[arg-type]

    assert updated.state_version == state.state_version + 1
    assert updated.stage is CatalogStage.EXTRACTED
    assert updated.normalization_result is None
    assert updated.candidate_profile is None
    assert updated.validation_result is None
    assert state.model_dump(mode="json") == original_dump


def test_normalization_requires_extraction_and_clears_downstream() -> None:
    updater = CatalogStateUpdater()
    with pytest.raises(InvalidStateTransitionError):
        updater.apply_normalization(
            create_initial_catalog_state(request()), normalization()
        )

    state = pipeline_state()
    updated = updater.apply_normalization(state, normalization())

    assert updated.extraction_result == state.extraction_result
    assert updated.candidate_profile is None
    assert updated.validation_result is None
    assert updated.stage is CatalogStage.NORMALIZED


def test_profile_requires_upstream_rejects_identity_and_clears_validation() -> None:
    updater = CatalogStateUpdater()
    initial = create_initial_catalog_state(request())
    profile = pipeline_state().candidate_profile
    assert profile is not None

    with pytest.raises(InvalidStateTransitionError):
        updater.apply_profile(initial, profile)

    normalized = updater.apply_normalization(
        updater.apply_extraction(initial, extraction()), normalization()
    )
    wrong_profile = profile.model_copy(update={"request_id": "OTHER"})
    with pytest.raises(InvalidStateTransitionError):
        updater.apply_profile(normalized, wrong_profile)

    updated = updater.apply_profile(pipeline_state(), profile)
    assert updated.validation_result is None
    assert updated.stage is CatalogStage.PROFILE_BUILT


def test_validation_requires_profile_and_maps_validity_to_status() -> None:
    updater = CatalogStateUpdater()
    with pytest.raises(InvalidStateTransitionError):
        updater.apply_validation(
            create_initial_catalog_state(request()), ValidationResult(valid=True)
        )

    state = pipeline_state()
    warning = ValidationIssue(
        code="WARNING_ONLY",
        field="requirements[0].confidence",
        severity=IssueSeverity.WARNING,
        category=IssueCategory.AMBIGUITY,
        message="Controlled warning.",
    )
    validated = updater.apply_validation(
        state, ValidationResult(valid=True, issues=[warning])
    )
    blocked = updater.apply_validation(state, invalid_validation())

    assert validated.status is CatalogStatus.PROCESSING
    assert validated.stage is CatalogStage.VALIDATED
    assert validated.published_project_id is None
    assert blocked.status is CatalogStatus.PROCESSING
    assert blocked.stage is CatalogStage.VALIDATED


@pytest.mark.parametrize(
    ("artifact_name", "action"),
    [
        ("extraction_result", RecoveryActionName.REEXTRACT_FIELD),
        ("normalization_result", RecoveryActionName.LOOKUP_TAXONOMY),
        ("candidate_profile", RecoveryActionName.REBUILD_PROFILE),
    ],
)
def test_artifact_recovery_invalidates_only_downstream(
    artifact_name: str,
    action: RecoveryActionName,
) -> None:
    updater = CatalogStateUpdater()
    state = pipeline_state()
    artifact = {
        "extraction_result": extraction("Recovered extraction."),
        "normalization_result": normalization(),
        "candidate_profile": state.candidate_profile,
    }[artifact_name]
    recovery = result(
        action,
        RecoveryStatus.SUCCEEDED,
        **{artifact_name: artifact},
    )

    updated = updater.apply_recovery_result(state, action_request(action), recovery)

    assert updated.state_version == state.state_version + 1
    assert len(updated.recovery_history) == 1
    assert get_retry_count(updated, action) == 1
    assert updated.validation_result is None
    if artifact_name == "extraction_result":
        assert updated.stage is CatalogStage.EXTRACTED
        assert updated.normalization_result is None
        assert updated.candidate_profile is None
    elif artifact_name == "normalization_result":
        assert updated.stage is CatalogStage.NORMALIZED
        assert updated.extraction_result == state.extraction_result
        assert updated.candidate_profile is None
    else:
        assert updated.stage is CatalogStage.PROFILE_BUILT
        assert updated.extraction_result == state.extraction_result
        assert updated.normalization_result == state.normalization_result


def test_clarification_and_escalation_recovery_preserve_artifacts() -> None:
    updater = CatalogStateUpdater()
    state = pipeline_state()
    clarify_action = action_request(RecoveryActionName.REQUEST_CLARIFICATION)
    clarified = updater.apply_recovery_result(
        state,
        clarify_action,
        result(
            RecoveryActionName.REQUEST_CLARIFICATION,
            RecoveryStatus.AWAITING_INPUT,
            changed=False,
            clarification_request=clarification(),
        ),
    )
    escalate_action = action_request(RecoveryActionName.ESCALATE)
    escalated = updater.apply_recovery_result(
        state,
        escalate_action,
        result(
            RecoveryActionName.ESCALATE,
            RecoveryStatus.ESCALATED,
            changed=False,
            escalation=escalation(),
        ),
    )

    assert clarified.status is CatalogStatus.AWAITING_CLARIFICATION
    assert clarified.stage is CatalogStage.AWAITING_CLARIFICATION
    assert clarified.pending_clarification == clarification()
    assert clarified.validation_result == state.validation_result
    assert escalated.status is CatalogStatus.ESCALATED
    assert escalated.stage is CatalogStage.ESCALATED
    assert escalated.escalation == escalation()
    assert escalated.candidate_profile == state.candidate_profile


def test_failed_recovery_records_error_history_retry_and_preserves_artifacts() -> None:
    updater = CatalogStateUpdater()
    state = pipeline_state()
    action = action_request(RecoveryActionName.REBUILD_PROFILE)
    failed = result(
        RecoveryActionName.REBUILD_PROFILE,
        RecoveryStatus.FAILED,
        changed=False,
        error_code="PROFILE_REBUILD_FAILED",
    )

    updated = updater.apply_recovery_result(state, action, failed)

    assert updated.status is CatalogStatus.RETRYABLE_FAILURE
    assert updated.stage is CatalogStage.VALIDATED
    assert updated.candidate_profile == state.candidate_profile
    assert updated.validation_result == state.validation_result
    assert updated.errors[0].code == "PROFILE_REBUILD_FAILED"
    assert updated.errors[0].retryable is True
    assert updated.recovery_history[0].error_code == "PROFILE_REBUILD_FAILED"
    assert get_retry_count(updated, RecoveryActionName.REBUILD_PROFILE) == 1
    assert updated.state_version == state.state_version + 1


def test_no_change_preserves_validation_and_history_sequences_are_monotonic() -> None:
    updater = CatalogStateUpdater()
    state = pipeline_state()
    action = action_request(RecoveryActionName.REBUILD_PROFILE)
    unchanged = result(
        RecoveryActionName.REBUILD_PROFILE,
        RecoveryStatus.NO_CHANGE,
        changed=False,
    )

    first = updater.apply_recovery_result(state, action, unchanged)
    second = updater.apply_recovery_result(first, action, unchanged)

    assert second.status is CatalogStatus.PROCESSING
    assert second.stage is CatalogStage.RECOVERY
    assert second.validation_result == state.validation_result
    assert [entry.sequence for entry in second.recovery_history] == [1, 2]
    assert get_retry_count(second, RecoveryActionName.REBUILD_PROFILE) == 2
    assert second.state_version == state.state_version + 2
    assert not hasattr(second.recovery_history[0], "candidate_profile")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda request_value, result_value: (
            request_value.model_copy(update={"request_id": "OTHER"}),
            result_value,
        ),
        lambda request_value, result_value: (
            request_value,
            result_value.model_copy(update={"request_id": "OTHER"}),
        ),
        lambda request_value, result_value: (
            request_value,
            result_value.model_copy(update={"action": RecoveryActionName.ESCALATE}),
        ),
        lambda request_value, result_value: (
            request_value,
            result_value.model_copy(update={"issue_code": "OTHER"}),
        ),
    ],
)
def test_recovery_identity_mismatches_are_rejected_without_mutation(
    mutate: Callable[
        [RecoveryActionRequest, RecoveryActionResult],
        tuple[RecoveryActionRequest, RecoveryActionResult],
    ],
) -> None:
    state = pipeline_state()
    before = state.model_dump(mode="json")
    request_value = action_request()
    result_value = result(
        RecoveryActionName.REBUILD_PROFILE,
        RecoveryStatus.NO_CHANGE,
        changed=False,
    )
    request_value, result_value = mutate(request_value, result_value)

    with pytest.raises(InvalidStateTransitionError):
        CatalogStateUpdater().apply_recovery_result(state, request_value, result_value)

    assert state.model_dump(mode="json") == before


def test_malformed_success_without_artifact_is_rejected() -> None:
    malformed = RecoveryActionResult.model_construct(
        request_id="STATE-001",
        action=RecoveryActionName.REBUILD_PROFILE,
        issue_code="CONTROLLED_ISSUE",
        status=RecoveryStatus.SUCCEEDED,
        changed=True,
        message="Malformed success.",
    )

    with pytest.raises(InvalidStateTransitionError):
        CatalogStateUpdater().apply_recovery_result(
            pipeline_state(), action_request(), malformed
        )


def test_add_error_sets_retryable_or_permanent_status() -> None:
    updater = CatalogStateUpdater()
    state = create_initial_catalog_state(request())
    retryable = AgentError(
        code="TEMPORARY",
        message="Temporary failure.",
        stage=CatalogStage.RECEIVED,
        retryable=True,
    )
    permanent = retryable.model_copy(update={"code": "PERMANENT", "retryable": False})

    first = updater.add_error(state, retryable)
    second = updater.add_error(first, AgentError.model_validate(permanent.model_dump()))

    assert first.status is CatalogStatus.RETRYABLE_FAILURE
    assert second.status is CatalogStatus.PERMANENT_FAILURE
    assert [error.code for error in second.errors] == ["TEMPORARY", "PERMANENT"]
    assert second.state_version == 3


@pytest.mark.parametrize(
    "payload_update",
    [
        {"normalization_result": normalization()},
        {"candidate_profile": pipeline_state().candidate_profile},
        {"validation_result": invalid_validation()},
        {
            "status": CatalogStatus.COMPLETED,
            "stage": CatalogStage.COMPLETED,
        },
        {
            "status": CatalogStatus.AWAITING_CLARIFICATION,
            "stage": CatalogStage.AWAITING_CLARIFICATION,
        },
        {
            "status": CatalogStatus.ESCALATED,
            "stage": CatalogStage.ESCALATED,
        },
        {"stage": CatalogStage.AWAITING_CLARIFICATION},
        {"stage": CatalogStage.ESCALATED},
        {"stage": CatalogStage.COMPLETED},
        {"retry_counts": {RecoveryActionName.REBUILD_PROFILE: -1}},
        {"state_version": 0},
    ],
)
def test_invalid_state_invariants_are_rejected(
    payload_update: dict[str, object],
) -> None:
    payload = create_initial_catalog_state(request()).model_dump()
    payload.update(payload_update)

    with pytest.raises(ValidationError):
        CatalogAgentState.model_validate(payload)


def test_clarification_and_escalation_cannot_coexist() -> None:
    payload = pipeline_state().model_dump()
    payload.update(
        status=CatalogStatus.AWAITING_CLARIFICATION,
        stage=CatalogStage.AWAITING_CLARIFICATION,
        pending_clarification=clarification(),
        escalation=escalation(),
    )

    with pytest.raises(ValidationError):
        CatalogAgentState.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "candidate_profile",
            pipeline_state().candidate_profile.model_copy(  # type: ignore[union-attr]
                update={"request_id": "OTHER"}
            ),
        ),
        (
            "pending_clarification",
            clarification().model_copy(update={"request_id": "OTHER"}),
        ),
        ("escalation", escalation().model_copy(update={"request_id": "OTHER"})),
    ],
)
def test_artifact_request_identity_is_enforced(field: str, value: object) -> None:
    state = pipeline_state()
    payload = state.model_dump()
    payload[field] = value
    if field == "pending_clarification":
        payload.update(
            status=CatalogStatus.AWAITING_CLARIFICATION,
            stage=CatalogStage.AWAITING_CLARIFICATION,
        )
    elif field == "escalation":
        payload.update(status=CatalogStatus.ESCALATED, stage=CatalogStage.ESCALATED)

    with pytest.raises(ValidationError):
        CatalogAgentState.model_validate(payload)


def test_history_identity_and_sequence_are_enforced() -> None:
    updater = CatalogStateUpdater()
    action = action_request()
    unchanged = result(
        RecoveryActionName.REBUILD_PROFILE,
        RecoveryStatus.NO_CHANGE,
        changed=False,
    )
    state = updater.apply_recovery_result(pipeline_state(), action, unchanged)
    payload = state.model_dump()
    payload["recovery_history"][0]["sequence"] = 2

    with pytest.raises(ValidationError):
        CatalogAgentState.model_validate(payload)


@pytest.mark.parametrize(
    "state_factory",
    [
        lambda: create_initial_catalog_state(request()),
        lambda: pipeline_state(valid=True),
        lambda: CatalogStateUpdater().apply_recovery_result(
            pipeline_state(),
            action_request(RecoveryActionName.REQUEST_CLARIFICATION),
            result(
                RecoveryActionName.REQUEST_CLARIFICATION,
                RecoveryStatus.AWAITING_INPUT,
                changed=False,
                clarification_request=clarification(),
            ),
        ),
        lambda: CatalogStateUpdater().apply_recovery_result(
            pipeline_state(),
            action_request(RecoveryActionName.ESCALATE),
            result(
                RecoveryActionName.ESCALATE,
                RecoveryStatus.ESCALATED,
                changed=False,
                escalation=escalation(),
            ),
        ),
    ],
)
def test_state_round_trips_through_json(
    state_factory: Callable[[], CatalogAgentState],
) -> None:
    state = state_factory()

    restored = CatalogAgentState.model_validate_json(state.model_dump_json())

    assert restored == state


def test_state_is_frozen_and_updater_does_not_share_nested_artifacts() -> None:
    state = pipeline_state()
    before = state.model_dump(mode="json")
    updated = CatalogStateUpdater().apply_normalization(state, normalization())

    with pytest.raises(ValidationError):
        state.status = CatalogStatus.PROCESSING  # type: ignore[misc]
    assert state.model_dump(mode="json") == before
    assert updated.request is not state.request
    assert updated.extraction_result is not state.extraction_result
