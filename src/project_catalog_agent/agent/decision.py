"""Pure deterministic next-step policy for catalog-agent state."""

import re

from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogDecision,
    CatalogDecisionPolicyConfig,
    CatalogStatus,
    DecisionReason,
    DecisionType,
    IssueSeverity,
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryHistoryEntry,
    RecoveryStatus,
    ValidationIssue,
)
from project_catalog_agent.errors import InvalidDecisionStateError

_REQUIREMENT_PATH = re.compile(r"^requirements\[(\d+)](?:\.[a-z_]+)?$")
_PROVENANCE_PATH = re.compile(
    r"^requirements\[(\d+)]\.provenance\[(\d+)](?:\.[a-z_]+)?$"
)
_UNRESOLVED_PATH = re.compile(
    r"^unresolved_requirements\[(\d+)](?:\.[a-z_]+(?:\[\d+])?)?$"
)

# Lower numbers have higher priority. ValidationResult order breaks ties.
_ISSUE_PRIORITY: dict[str, int] = {
    **dict.fromkeys(
        (
            "DUPLICATE_CANONICAL_SKILL",
            "UNRESOLVED_LIST_MISMATCH",
            "EMPTY_PROVENANCE",
            "PROVENANCE_SKILL_INDEX_DUPLICATE",
            "PROVENANCE_IMPORTANCE_CONFLICT",
            "PROVENANCE_LEVEL_CONFLICT",
            "SOURCE_INDEX_COLLISION",
            "DUPLICATE_UNRESOLVED_SOURCE_INDEX",
        ),
        1,
    ),
    **dict.fromkeys(
        (
            "UNKNOWN_SKILL_ID",
            "CANONICAL_NAME_MISMATCH",
            "INACTIVE_SKILL",
            "UNKNOWN_CANDIDATE_SKILL_ID",
            "DUPLICATE_CANDIDATE_SKILL_ID",
        ),
        2,
    ),
    **dict.fromkeys(
        (
            "MISSING_REQUIRED_LEVEL",
            "EVIDENCE_NOT_VERBATIM",
            "PROVENANCE_EVIDENCE_NOT_VERBATIM",
            "NO_RESOLVED_REQUIREMENTS",
        ),
        3,
    ),
    **dict.fromkeys(
        (
            "NEEDS_REVIEW_REQUIREMENT",
            "MISSING_REVIEW_CANDIDATES",
            "UNMAPPED_REQUIREMENT",
        ),
        4,
    ),
}

_BUILDER_ISSUES = {
    "DUPLICATE_CANONICAL_SKILL",
    "UNRESOLVED_LIST_MISMATCH",
    "EMPTY_PROVENANCE",
    "PROVENANCE_SKILL_INDEX_DUPLICATE",
    "PROVENANCE_IMPORTANCE_CONFLICT",
    "PROVENANCE_LEVEL_CONFLICT",
    "SOURCE_INDEX_COLLISION",
    "DUPLICATE_UNRESOLVED_SOURCE_INDEX",
    "CANONICAL_NAME_MISMATCH",
    "DUPLICATE_CANDIDATE_SKILL_ID",
}
_EXTRACTION_ISSUES = {
    "MISSING_REQUIRED_LEVEL",
    "EVIDENCE_NOT_VERBATIM",
    "PROVENANCE_EVIDENCE_NOT_VERBATIM",
    "LOW_EXTRACTION_CONFIDENCE",
}
_TAXONOMY_ISSUES = {
    "UNKNOWN_SKILL_ID",
    "INACTIVE_SKILL",
    "UNKNOWN_CANDIDATE_SKILL_ID",
    "UNMAPPED_REQUIREMENT",
}
_AMBIGUOUS_ISSUES = {"NEEDS_REVIEW_REQUIREMENT", "MISSING_REVIEW_CANDIDATES"}


class CatalogDecisionPolicy:
    """Select one next step without executing it or changing state."""

    def __init__(self, config: CatalogDecisionPolicyConfig | None = None) -> None:
        self._config = config or CatalogDecisionPolicyConfig()

    def decide(self, state: CatalogAgentState) -> CatalogDecision:
        """Return the same structured decision for the same state and config."""
        state = self._validated_state(state)
        self._validate_retry_accounting(state)
        if state.status is CatalogStatus.COMPLETED:
            return self._simple(
                DecisionType.COMPLETE,
                DecisionReason.PROFILE_PUBLISHED,
                "The validated profile has been published.",
            )
        if state.status is CatalogStatus.ESCALATED or state.escalation is not None:
            return self._simple(
                DecisionType.STOP_ESCALATED,
                DecisionReason.ALREADY_ESCALATED,
                "The request already has a structured escalation.",
            )
        if (
            state.status is CatalogStatus.AWAITING_CLARIFICATION
            or state.pending_clarification is not None
        ):
            return self._simple(
                DecisionType.WAIT_FOR_CLARIFICATION,
                DecisionReason.AWAITING_CLARIFICATION,
                "Processing is waiting for a clarification answer.",
            )
        if state.status is CatalogStatus.PERMANENT_FAILURE:
            return self._simple(
                DecisionType.STOP_PERMANENT_FAILURE,
                DecisionReason.PERMANENT_FAILURE,
                "The request is in a permanent-failure state.",
            )
        if state.extraction_result is None:
            return self._simple(
                DecisionType.RUN_EXTRACTION,
                DecisionReason.EXTRACTION_REQUIRED,
                "Requirement extraction is the next pipeline step.",
            )
        if state.normalization_result is None:
            return self._simple(
                DecisionType.RUN_NORMALIZATION,
                DecisionReason.NORMALIZATION_REQUIRED,
                "Taxonomy normalization is the next pipeline step.",
            )
        if state.candidate_profile is None:
            return self._simple(
                DecisionType.BUILD_PROFILE,
                DecisionReason.PROFILE_BUILD_REQUIRED,
                "Candidate profile construction is the next pipeline step.",
            )
        if state.validation_result is None:
            return self._simple(
                DecisionType.RUN_VALIDATION,
                DecisionReason.VALIDATION_REQUIRED,
                "Profile validation is the next pipeline step.",
            )
        if state.validation_result.valid:
            return self._simple(
                DecisionType.PUBLISH_PROFILE,
                DecisionReason.PROFILE_READY_TO_PUBLISH,
                "The validated profile is ready for persistence and publication.",
            )

        blocking = [
            issue
            for issue in state.validation_result.issues
            if issue.severity is IssueSeverity.BLOCKING
        ]
        if not blocking:
            raise InvalidDecisionStateError(
                "invalid validation result contains no blocking issue"
            )
        issue = min(
            enumerate(blocking),
            key=lambda item: (_ISSUE_PRIORITY.get(item[1].code, 99), item[0]),
        )[1]
        return self._decide_recovery(state, issue)

    def _decide_recovery(
        self,
        state: CatalogAgentState,
        issue: ValidationIssue,
    ) -> CatalogDecision:
        permitted = set(issue.resolvable_by)
        known_issue = (
            issue.code in _ISSUE_PRIORITY or issue.code == "LOW_EXTRACTION_CONFIDENCE"
        )
        if not known_issue:
            return self._escalate_or_stop(
                state, issue, permitted, DecisionReason.NO_SAFE_ACTION
            )

        if len(state.recovery_history) >= self._config.max_total_recovery_attempts:
            return self._escalate_or_stop(
                state, issue, permitted, DecisionReason.RETRY_LIMIT_REACHED
            )

        preferences = self._preferences(issue.code)
        saw_no_progress = False
        saw_limit = False
        for action in preferences:
            if action.value not in permitted:
                continue
            if action is RecoveryActionName.ESCALATE:
                reason = (
                    DecisionReason.NO_PROGRESS_DETECTED
                    if saw_no_progress
                    else (
                        DecisionReason.RETRY_LIMIT_REACHED
                        if saw_limit
                        else DecisionReason.NO_SAFE_ACTION
                    )
                )
                return self._escalate_or_stop(state, issue, permitted, reason)
            attempts = self._issue_action_history(state, issue, action)
            if action is RecoveryActionName.REQUEST_CLARIFICATION and attempts:
                saw_limit = True
                continue
            if attempts and attempts[-1].status is RecoveryStatus.NO_CHANGE:
                saw_no_progress = True
                if self._config.escalate_after_no_change:
                    return self._escalate_or_stop(
                        state,
                        issue,
                        permitted,
                        DecisionReason.NO_PROGRESS_DETECTED,
                    )
                continue
            if len(attempts) >= self._limit(action):
                saw_limit = True
                continue
            if not self._safe_target(issue, action):
                continue
            reason = (
                DecisionReason.CLARIFICATION_REQUIRED
                if action is RecoveryActionName.REQUEST_CLARIFICATION
                else DecisionReason.AUTOMATIC_RECOVERY_AVAILABLE
            )
            return self._recovery_decision(
                state, issue, action, len(attempts) + 1, reason
            )

        reason = (
            DecisionReason.NO_PROGRESS_DETECTED
            if saw_no_progress
            else DecisionReason.RETRY_LIMIT_REACHED
            if saw_limit
            else DecisionReason.NO_SAFE_ACTION
        )
        return self._escalate_or_stop(state, issue, permitted, reason)

    def _escalate_or_stop(
        self,
        state: CatalogAgentState,
        issue: ValidationIssue,
        permitted: set[str],
        reason: DecisionReason,
    ) -> CatalogDecision:
        escalation_attempts = self._issue_action_history(
            state, issue, RecoveryActionName.ESCALATE
        )
        if (
            self._config.escalate_on_no_safe_action
            and RecoveryActionName.ESCALATE.value in permitted
            and not escalation_attempts
        ):
            return self._recovery_decision(
                state, issue, RecoveryActionName.ESCALATE, 1, reason
            )
        return CatalogDecision(
            decision_type=DecisionType.STOP_PERMANENT_FAILURE,
            reason_code=reason,
            message="No safe permitted recovery action remains.",
            selected_issue_code=issue.code,
            selected_issue_field=issue.field,
        )

    def _recovery_decision(
        self,
        state: CatalogAgentState,
        issue: ValidationIssue,
        action: RecoveryActionName,
        attempt_number: int,
        reason: DecisionReason,
    ) -> CatalogDecision:
        try:
            request = RecoveryActionRequest(
                request_id=state.request.request_id,
                action=action,
                issue_code=issue.code,
                issue_field=issue.field,
                attempt_number=attempt_number,
                context={},
            )
        except ValidationError as error:
            raise InvalidDecisionStateError(
                "selected issue field cannot form a safe recovery target"
            ) from error
        return CatalogDecision(
            decision_type=DecisionType.EXECUTE_RECOVERY,
            reason_code=reason,
            message=f"Execute {action.value} for the selected validation issue.",
            action_request=request,
            selected_issue_code=issue.code,
            selected_issue_field=issue.field,
        )

    @staticmethod
    def _preferences(code: str) -> tuple[RecoveryActionName, ...]:
        if code in _BUILDER_ISSUES:
            return (
                RecoveryActionName.REBUILD_PROFILE,
                RecoveryActionName.ESCALATE,
            )
        if code == "NO_RESOLVED_REQUIREMENTS":
            return (
                RecoveryActionName.REEXTRACT_FIELD,
                RecoveryActionName.LOOKUP_TAXONOMY,
                RecoveryActionName.REQUEST_CLARIFICATION,
                RecoveryActionName.ESCALATE,
            )
        if code in _EXTRACTION_ISSUES:
            return (
                RecoveryActionName.REEXTRACT_FIELD,
                RecoveryActionName.REQUEST_CLARIFICATION,
                RecoveryActionName.ESCALATE,
            )
        if code in _TAXONOMY_ISSUES:
            return (
                RecoveryActionName.LOOKUP_TAXONOMY,
                RecoveryActionName.RECONSIDER_MAPPING,
                RecoveryActionName.REQUEST_CLARIFICATION,
                RecoveryActionName.ESCALATE,
            )
        if code in _AMBIGUOUS_ISSUES:
            return (
                RecoveryActionName.RECONSIDER_MAPPING,
                RecoveryActionName.REQUEST_CLARIFICATION,
                RecoveryActionName.ESCALATE,
            )
        return ()

    def _limit(self, action: RecoveryActionName) -> int:
        return {
            RecoveryActionName.REBUILD_PROFILE: self._config.max_rebuild_attempts,
            RecoveryActionName.REEXTRACT_FIELD: self._config.max_reextraction_attempts,
            RecoveryActionName.LOOKUP_TAXONOMY: self._config.max_taxonomy_lookup_attempts,
            RecoveryActionName.RECONSIDER_MAPPING: self._config.max_mapping_reconsideration_attempts,
            RecoveryActionName.REQUEST_CLARIFICATION: self._config.max_clarification_requests_per_issue,
            RecoveryActionName.ESCALATE: 1,
        }[action]

    @staticmethod
    def _issue_action_history(
        state: CatalogAgentState,
        issue: ValidationIssue,
        action: RecoveryActionName,
    ) -> list[RecoveryHistoryEntry]:
        return [
            entry
            for entry in state.recovery_history
            if entry.action_request.issue_code == issue.code
            and entry.action_request.issue_field == issue.field
            and entry.action_request.action is action
        ]

    @staticmethod
    def _safe_target(issue: ValidationIssue, action: RecoveryActionName) -> bool:
        if action in {RecoveryActionName.REBUILD_PROFILE, RecoveryActionName.ESCALATE}:
            return True
        if issue.code == "NO_RESOLVED_REQUIREMENTS" and action in {
            RecoveryActionName.REEXTRACT_FIELD,
            RecoveryActionName.LOOKUP_TAXONOMY,
        }:
            return True
        return any(
            pattern.fullmatch(issue.field) is not None
            for pattern in (_PROVENANCE_PATH, _REQUIREMENT_PATH, _UNRESOLVED_PATH)
        )

    @staticmethod
    def _validate_retry_accounting(state: CatalogAgentState) -> None:
        history_counts: dict[RecoveryActionName, int] = {}
        for entry in state.recovery_history:
            action = entry.action_request.action
            history_counts[action] = history_counts.get(action, 0) + 1
        if any(
            state.retry_counts.get(action, 0) != count
            for action, count in history_counts.items()
        ) or any(
            action not in history_counts and count != 0
            for action, count in state.retry_counts.items()
        ):
            raise InvalidDecisionStateError(
                "retry counts do not match recovery history"
            )

    @staticmethod
    def _validated_state(state: CatalogAgentState) -> CatalogAgentState:
        try:
            return CatalogAgentState.model_validate(state.model_dump())
        except ValidationError as error:
            raise InvalidDecisionStateError("catalog state is invalid") from error

    @staticmethod
    def _simple(
        decision_type: DecisionType,
        reason: DecisionReason,
        message: str,
    ) -> CatalogDecision:
        return CatalogDecision(
            decision_type=decision_type,
            reason_code=reason,
            message=message,
        )
