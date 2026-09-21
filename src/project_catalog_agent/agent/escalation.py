"""Deterministic application of authenticated escalation reviews."""

from pydantic import ValidationError

from project_catalog_agent.admin import (
    AdminAuthorizer,
    AdminRole,
    EscalationReviewResponse,
    EscalationReviewResult,
    EscalationReviewStatus,
)
from project_catalog_agent.agent.state import CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    EscalationReviewHistoryEntry,
)
from project_catalog_agent.errors import InvalidStateTransitionError


class EscalationReviewProcessor:
    """Verify and record a bounded human review without publishing a project."""

    def __init__(
        self,
        *,
        state_updater: CatalogStateUpdater,
        admin_authorizer: AdminAuthorizer,
    ) -> None:
        self._state_updater = state_updater
        self._admin_authorizer = admin_authorizer

    def apply(
        self,
        *,
        state: CatalogAgentState,
        response: EscalationReviewResponse,
    ) -> EscalationReviewResult:
        """Record an authorized current review or return a stable rejection."""
        escalation = state.escalation
        if (
            state.status is not CatalogStatus.ESCALATED
            or state.stage is not CatalogStage.ESCALATED
            or escalation is None
        ):
            return self._reject(response, "NO_CURRENT_ESCALATION")
        if response.request_id != state.request.request_id:
            return self._reject(response, "REQUEST_ID_MISMATCH")
        if escalation.request_id != state.request.request_id:
            return self._reject(response, "REQUEST_ID_MISMATCH")
        if response.escalation_id != escalation.escalation_id:
            return self._reject(response, "ESCALATION_ID_MISMATCH")
        if any(
            entry.escalation_id == response.escalation_id
            for entry in state.escalation_review_history
        ):
            return self._reject(response, "ESCALATION_ALREADY_REVIEWED")
        if not self._admin_authorizer.is_authorized(
            actor_id=response.reviewed_by,
            required_role=AdminRole.ESCALATOR,
        ):
            return self._reject(response, "UNAUTHORIZED_RESPONDENT")
        history = EscalationReviewHistoryEntry(
            sequence=len(state.escalation_review_history) + 1,
            request_id=response.request_id,
            escalation_id=response.escalation_id,
            reviewed_by=response.reviewed_by,
            decision=response.decision.value,
            review_note=response.review_note,
            submitted_at=response.submitted_at,
        )
        try:
            updated = self._state_updater.apply_escalation_review(state, history)
        except (InvalidStateTransitionError, ValidationError):
            return self._reject(response, "REVIEW_APPLICATION_FAILED")
        return EscalationReviewResult(
            request_id=response.request_id,
            escalation_id=response.escalation_id,
            status=EscalationReviewStatus.APPLIED,
            changed=True,
            updated_state=updated,
            message="The escalation review was recorded.",
        )

    @staticmethod
    def _reject(
        response: EscalationReviewResponse,
        error_code: str,
    ) -> EscalationReviewResult:
        return EscalationReviewResult(
            request_id=response.request_id,
            escalation_id=response.escalation_id,
            status=EscalationReviewStatus.REJECTED,
            changed=False,
            message="The escalation review was rejected.",
            error_code=error_code,
        )
