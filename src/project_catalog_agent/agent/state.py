"""Deterministic updates for the unified catalog-agent state."""

from typing import Any, NoReturn

from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    AgentError,
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ClarificationHistoryEntry,
    EscalationReviewHistoryEntry,
    ProjectProfile,
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryActionResult,
    RecoveryHistoryEntry,
    RecoveryStatus,
    RequirementExtractionResult,
    TaxonomyNormalizationResult,
    ValidationResult,
)
from project_catalog_agent.errors import InvalidStateTransitionError


class CatalogStateUpdater:
    """Apply explicit state transitions without mutating prior state."""

    def apply_extraction(
        self,
        state: CatalogAgentState,
        extraction_result: RequirementExtractionResult,
    ) -> CatalogAgentState:
        """Store extraction and invalidate every downstream artifact."""
        return self._transition(
            state,
            extraction_result=extraction_result,
            normalization_result=None,
            candidate_profile=None,
            validation_result=None,
            pending_clarification=None,
            escalation=None,
            status=CatalogStatus.PROCESSING,
            stage=CatalogStage.EXTRACTED,
        )

    def apply_normalization(
        self,
        state: CatalogAgentState,
        normalization_result: TaxonomyNormalizationResult,
    ) -> CatalogAgentState:
        """Store normalization after extraction and invalidate downstream data."""
        if state.extraction_result is None:
            self._invalid("normalization cannot be applied before extraction")
        return self._transition(
            state,
            normalization_result=normalization_result,
            candidate_profile=None,
            validation_result=None,
            pending_clarification=None,
            escalation=None,
            status=CatalogStatus.PROCESSING,
            stage=CatalogStage.NORMALIZED,
        )

    def apply_profile(
        self,
        state: CatalogAgentState,
        profile: ProjectProfile,
    ) -> CatalogAgentState:
        """Store a candidate profile after both upstream artifacts exist."""
        if state.extraction_result is None or state.normalization_result is None:
            self._invalid("profile cannot be applied before normalization")
        if profile.request_id != state.request.request_id:
            self._invalid("profile request_id does not match state request")
        return self._transition(
            state,
            candidate_profile=profile,
            validation_result=None,
            pending_clarification=None,
            escalation=None,
            status=CatalogStatus.PROCESSING,
            stage=CatalogStage.PROFILE_BUILT,
        )

    def apply_validation(
        self,
        state: CatalogAgentState,
        validation_result: ValidationResult,
    ) -> CatalogAgentState:
        """Store validation and complete only a valid candidate profile."""
        if state.candidate_profile is None:
            self._invalid("validation cannot be applied before a profile")
        return self._transition(
            state,
            validation_result=validation_result,
            pending_clarification=None,
            escalation=None,
            published_project_id=None,
            status=CatalogStatus.PROCESSING,
            stage=CatalogStage.VALIDATED,
        )

    def apply_publication(
        self,
        state: CatalogAgentState,
        *,
        project_id: str,
    ) -> CatalogAgentState:
        """Complete one state only after its valid profile has been persisted."""
        if not project_id.strip():
            self._invalid("published project ID is required")
        if state.candidate_profile is None or state.validation_result is None:
            self._invalid("publication requires a validated candidate profile")
        if not state.validation_result.valid:
            self._invalid("publication requires valid validation")
        if state.pending_clarification is not None or state.escalation is not None:
            self._invalid("publication cannot bypass protected pending work")
        return self._transition(
            state,
            published_project_id=project_id.strip(),
            status=CatalogStatus.COMPLETED,
            stage=CatalogStage.COMPLETED,
        )

    def apply_recovery_result(
        self,
        state: CatalogAgentState,
        action_request: RecoveryActionRequest,
        recovery_result: RecoveryActionResult,
    ) -> CatalogAgentState:
        """Record and apply exactly one already-executed recovery result."""
        action_request = self._validated_action_request(action_request)
        recovery_result = self._validated_recovery_result(recovery_result)
        self._validate_recovery_identity(state, action_request, recovery_result)

        artifact_count = sum(
            artifact is not None
            for artifact in (
                recovery_result.extraction_result,
                recovery_result.normalization_result,
                recovery_result.candidate_profile,
            )
        )
        if recovery_result.status is RecoveryStatus.SUCCEEDED and artifact_count != 1:
            self._invalid("successful recovery must produce exactly one artifact")

        history = [
            *state.recovery_history,
            self._history_entry(state, action_request, recovery_result),
        ]
        retry_counts = dict(state.retry_counts)
        retry_counts[action_request.action] = (
            retry_counts.get(action_request.action, 0) + 1
        )
        updates: dict[str, Any] = {
            "recovery_history": history,
            "retry_counts": retry_counts,
        }

        if recovery_result.extraction_result is not None:
            updates.update(
                extraction_result=recovery_result.extraction_result,
                normalization_result=None,
                candidate_profile=None,
                validation_result=None,
                pending_clarification=None,
                escalation=None,
                status=CatalogStatus.PROCESSING,
                stage=CatalogStage.EXTRACTED,
            )
        elif recovery_result.normalization_result is not None:
            if state.extraction_result is None:
                self._invalid("normalization recovery requires extraction")
            updates.update(
                normalization_result=recovery_result.normalization_result,
                candidate_profile=None,
                validation_result=None,
                pending_clarification=None,
                escalation=None,
                status=CatalogStatus.PROCESSING,
                stage=CatalogStage.NORMALIZED,
            )
        elif recovery_result.candidate_profile is not None:
            if state.extraction_result is None or state.normalization_result is None:
                self._invalid("profile recovery requires upstream artifacts")
            if recovery_result.candidate_profile.request_id != state.request.request_id:
                self._invalid("recovered profile request_id does not match state")
            updates.update(
                candidate_profile=recovery_result.candidate_profile,
                validation_result=None,
                pending_clarification=None,
                escalation=None,
                status=CatalogStatus.PROCESSING,
                stage=CatalogStage.PROFILE_BUILT,
            )
        elif recovery_result.status is RecoveryStatus.AWAITING_INPUT:
            updates.update(
                pending_clarification=recovery_result.clarification_request,
                escalation=None,
                status=CatalogStatus.AWAITING_CLARIFICATION,
                stage=CatalogStage.AWAITING_CLARIFICATION,
            )
        elif recovery_result.status is RecoveryStatus.ESCALATED:
            updates.update(
                escalation=recovery_result.escalation,
                pending_clarification=None,
                status=CatalogStatus.ESCALATED,
                stage=CatalogStage.ESCALATED,
            )
        elif recovery_result.status is RecoveryStatus.FAILED:
            if recovery_result.error_code is None:
                self._invalid("failed recovery requires an error code")
            errors = [
                *state.errors,
                AgentError(
                    code=recovery_result.error_code,
                    message=recovery_result.message,
                    stage=CatalogStage.RECOVERY,
                    retryable=True,
                    action=action_request.action,
                    issue_code=action_request.issue_code,
                    field=action_request.issue_field,
                ),
            ]
            updates.update(
                errors=errors,
                status=CatalogStatus.RETRYABLE_FAILURE,
            )
        elif recovery_result.status is RecoveryStatus.NO_CHANGE:
            updates.update(
                status=CatalogStatus.PROCESSING,
                stage=CatalogStage.RECOVERY,
            )
        else:
            self._invalid("recovery status does not match its payload")
        return self._transition(state, **updates)

    def add_error(
        self,
        state: CatalogAgentState,
        error: AgentError,
    ) -> CatalogAgentState:
        """Record an operational error without changing current artifacts."""
        return self._transition(
            state,
            errors=[*state.errors, error],
            status=(
                CatalogStatus.RETRYABLE_FAILURE
                if error.retryable
                else CatalogStatus.PERMANENT_FAILURE
            ),
        )

    def apply_clarification_update(
        self,
        state: CatalogAgentState,
        *,
        history_entry: ClarificationHistoryEntry,
        updated_extraction: RequirementExtractionResult | None = None,
        updated_normalization: TaxonomyNormalizationResult | None = None,
    ) -> CatalogAgentState:
        """Apply exactly one clarified artifact in one versioned transition."""
        if (updated_extraction is None) == (updated_normalization is None):
            self._invalid("clarification must update exactly one artifact")
        if history_entry.sequence != len(state.clarification_history) + 1:
            self._invalid("clarification history sequence is invalid")
        common: dict[str, Any] = {
            "clarification_history": [
                *state.clarification_history,
                history_entry,
            ],
            "candidate_profile": None,
            "validation_result": None,
            "pending_clarification": None,
            "escalation": None,
            "status": CatalogStatus.PROCESSING,
        }
        if updated_extraction is not None:
            common.update(
                extraction_result=updated_extraction,
                normalization_result=None,
                stage=CatalogStage.EXTRACTED,
            )
        else:
            if state.extraction_result is None:
                self._invalid("clarified normalization requires extraction")
            common.update(
                normalization_result=updated_normalization,
                stage=CatalogStage.NORMALIZED,
            )
        return self._transition(state, **common)

    def apply_escalation_review(
        self,
        state: CatalogAgentState,
        history_entry: EscalationReviewHistoryEntry,
    ) -> CatalogAgentState:
        """Record one bounded review while leaving the project escalated."""
        if state.escalation is None or state.stage is not CatalogStage.ESCALATED:
            self._invalid("escalation review requires a current escalation")
        if history_entry.sequence != len(state.escalation_review_history) + 1:
            self._invalid("escalation review history sequence is invalid")
        return self._transition(
            state,
            escalation_review_history=[
                *state.escalation_review_history,
                history_entry,
            ],
            status=CatalogStatus.ESCALATED,
            stage=CatalogStage.ESCALATED,
        )

    @staticmethod
    def _history_entry(
        state: CatalogAgentState,
        action_request: RecoveryActionRequest,
        result: RecoveryActionResult,
    ) -> RecoveryHistoryEntry:
        return RecoveryHistoryEntry(
            sequence=len(state.recovery_history) + 1,
            action_request=action_request.model_copy(deep=True),
            status=result.status,
            changed=result.changed,
            error_code=result.error_code,
            message=result.message,
            produced_extraction_result=result.extraction_result is not None,
            produced_normalization_result=result.normalization_result is not None,
            produced_candidate_profile=result.candidate_profile is not None,
            produced_clarification_request=result.clarification_request is not None,
            produced_escalation=result.escalation is not None,
        )

    @staticmethod
    def _validate_recovery_identity(
        state: CatalogAgentState,
        request: RecoveryActionRequest,
        result: RecoveryActionResult,
    ) -> None:
        if request.request_id != state.request.request_id:
            raise InvalidStateTransitionError(
                "recovery request_id does not match state request"
            )
        if result.request_id != state.request.request_id:
            raise InvalidStateTransitionError(
                "recovery result request_id does not match state request"
            )
        if result.action is not request.action:
            raise InvalidStateTransitionError(
                "recovery result action does not match action request"
            )
        if result.issue_code != request.issue_code:
            raise InvalidStateTransitionError(
                "recovery result issue does not match action request"
            )

    @staticmethod
    def _validated_action_request(
        request: RecoveryActionRequest,
    ) -> RecoveryActionRequest:
        try:
            return RecoveryActionRequest.model_validate(request.model_dump())
        except ValidationError as error:
            raise InvalidStateTransitionError(
                "recovery action request is invalid"
            ) from error

    @staticmethod
    def _validated_recovery_result(
        result: RecoveryActionResult,
    ) -> RecoveryActionResult:
        try:
            return RecoveryActionResult.model_validate(result.model_dump())
        except ValidationError as error:
            raise InvalidStateTransitionError("recovery result is invalid") from error

    @staticmethod
    def _transition(
        state: CatalogAgentState,
        **updates: Any,
    ) -> CatalogAgentState:
        payload = state.model_dump()
        payload.update(updates)
        payload["state_version"] = state.state_version + 1
        try:
            return CatalogAgentState.model_validate(payload)
        except ValidationError as error:
            raise InvalidStateTransitionError("state transition is invalid") from error

    @staticmethod
    def _invalid(message: str) -> NoReturn:
        raise InvalidStateTransitionError(message)


def get_retry_count(
    state: CatalogAgentState,
    action: RecoveryActionName,
) -> int:
    """Return zero when an action has no recorded recovery attempts."""
    return state.retry_counts.get(action, 0)
