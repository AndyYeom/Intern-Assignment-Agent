"""Credential-safe terminal adapters for V1 administrator workflows."""

import getpass
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from project_catalog_agent.admin.audit import AuditSink
from project_catalog_agent.admin.authentication import AdminAuthenticator
from project_catalog_agent.admin.contracts import (
    AdminAuditEvent,
    AuthenticationResult,
    AuthenticationStatus,
    EscalationDecision,
    EscalationReviewResponse,
    EscalationReviewResult,
    EscalationReviewStatus,
)
from project_catalog_agent.admin.roles import AdminRole
from project_catalog_agent.agent.clarification import ClarificationResponseProcessor
from project_catalog_agent.agent.escalation import EscalationReviewProcessor
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    ClarificationApplicationResult,
    ClarificationApplicationStatus,
    ClarificationResponse,
)

InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]
Clock = Callable[[], datetime]


class TerminalAdminLogin:
    """Read hidden credentials with a bounded number of attempts."""

    def __init__(
        self,
        *,
        authenticator: AdminAuthenticator,
        max_attempts: int = 3,
        input_reader: InputReader = input,
        password_reader: InputReader = getpass.getpass,
        output_writer: OutputWriter = print,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self._authenticator = authenticator
        self._max_attempts = max_attempts
        self._input_reader = input_reader
        self._password_reader = password_reader
        self._output_writer = output_writer

    def login(self, *, required_role: AdminRole) -> AuthenticationResult:
        """Authenticate without echoing or retaining the supplied password."""
        try:
            for _ in range(self._max_attempts):
                username = self._input_reader("Username: ")
                password = self._password_reader("Password: ")
                result = self._authenticator.authenticate(
                    username=username,
                    password=password,
                    required_role=required_role,
                )
                if result.status is AuthenticationStatus.AUTHENTICATED:
                    return result
                self._output_writer("Authentication failed.")
        except (EOFError, KeyboardInterrupt):
            self._output_writer("Authentication cancelled.")
            return _authentication_rejection("AUTHENTICATION_CANCELLED")
        return _authentication_rejection("MAX_AUTHENTICATION_ATTEMPTS")


class TerminalClarificationHandler:
    """Collect one safe clarification answer and delegate its application."""

    def __init__(
        self,
        *,
        login: TerminalAdminLogin,
        processor: ClarificationResponseProcessor,
        audit_sink: AuditSink,
        input_reader: InputReader = input,
        output_writer: OutputWriter = print,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._login = login
        self._processor = processor
        self._audit_sink = audit_sink
        self._input_reader = input_reader
        self._output_writer = output_writer
        self._clock = clock

    def handle(self, *, state: CatalogAgentState) -> ClarificationApplicationResult:
        """Authenticate a clarifier, map terminal input, and call the processor."""
        pending = state.pending_clarification
        if pending is None:
            return _clarification_rejection(
                state.request.request_id,
                "unavailable",
                "NO_PENDING_CLARIFICATION",
            )
        self._output_writer(f"Clarification: {pending.clarification_id}")
        self._output_writer(pending.question)
        for index, option in enumerate(pending.options, start=1):
            self._output_writer(f"{index}. {option.label}")
        if pending.allow_free_text:
            self._output_writer("Free text is allowed.")
        self._output_writer(f"{len(pending.options) + 1}. Cancel")

        authentication = self._login.login(required_role=AdminRole.CLARIFIER)
        if authentication.status is not AuthenticationStatus.AUTHENTICATED:
            return _clarification_rejection(
                state.request.request_id,
                pending.clarification_id,
                authentication.error_code or "AUTHENTICATION_REJECTED",
            )
        actor_id = authentication.actor_id
        if actor_id is None:
            return _clarification_rejection(
                state.request.request_id,
                pending.clarification_id,
                "AUTHENTICATION_REJECTED",
            )

        selected_value: str | None = None
        free_text: str | None = None
        try:
            if pending.options:
                prompt = "Option number"
                if pending.allow_free_text:
                    prompt += " (0 for free text)"
                choice = self._input_reader(f"{prompt}: ").strip()
                if choice.casefold() in {"q", "cancel"} or choice == str(
                    len(pending.options) + 1
                ):
                    return self._rejected_after_authentication(
                        state,
                        actor_id,
                        "TERMINAL_INPUT_CANCELLED",
                        outcome="cancelled",
                    )
                if choice == "0" and pending.allow_free_text:
                    free_text = self._input_reader("Free text: ")
                else:
                    try:
                        option_index = int(choice) - 1
                    except ValueError:
                        return self._rejected_after_authentication(
                            state, actor_id, "INVALID_SELECTED_OPTION"
                        )
                    if option_index < 0 or option_index >= len(pending.options):
                        return self._rejected_after_authentication(
                            state, actor_id, "INVALID_SELECTED_OPTION"
                        )
                    selected_value = pending.options[option_index].value
            elif pending.allow_free_text:
                free_text = self._input_reader("Free text: ")
            else:
                return self._rejected_after_authentication(
                    state, actor_id, "INVALID_ANSWER_FORM"
                )
        except (EOFError, KeyboardInterrupt):
            return self._rejected_after_authentication(
                state, actor_id, "TERMINAL_INPUT_CANCELLED", outcome="cancelled"
            )

        try:
            response = ClarificationResponse(
                request_id=state.request.request_id,
                clarification_id=pending.clarification_id,
                answered_by=actor_id,
                selected_value=selected_value,
                free_text=free_text,
                submitted_at=self._clock(),
            )
        except ValueError:
            return self._rejected_after_authentication(
                state, actor_id, "INVALID_ANSWER_FORM"
            )
        result = self._processor.apply(state=state, response=response)
        outcome = (
            "succeeded"
            if result.status is ClarificationApplicationStatus.APPLIED
            else "rejected"
        )
        self._record_event(
            actor_id=actor_id,
            request_id=state.request.request_id,
            target_id=pending.clarification_id,
            outcome=outcome,
        )
        self._output_writer(
            "Clarification applied."
            if outcome == "succeeded"
            else "Clarification rejected."
        )
        return result

    def _rejected_after_authentication(
        self,
        state: CatalogAgentState,
        actor_id: str,
        error_code: str,
        *,
        outcome: str = "rejected",
    ) -> ClarificationApplicationResult:
        pending = state.pending_clarification
        target_id = pending.clarification_id if pending is not None else "unavailable"
        self._record_event(
            actor_id=actor_id,
            request_id=state.request.request_id,
            target_id=target_id,
            outcome=outcome,
        )
        self._output_writer("Clarification rejected.")
        return _clarification_rejection(state.request.request_id, target_id, error_code)

    def _record_event(
        self,
        *,
        actor_id: str,
        request_id: str,
        target_id: str,
        outcome: str,
    ) -> None:
        self._audit_sink.record(
            AdminAuditEvent(
                event_id=str(uuid4()),
                actor_id=actor_id,
                role=AdminRole.CLARIFIER,
                operation="answer_clarification",
                request_id=request_id,
                target_id=target_id,
                outcome=outcome,
                occurred_at=self._clock(),
            )
        )


class TerminalEscalationHandler:
    """Collect one bounded escalation review from an authenticated escalator."""

    def __init__(
        self,
        *,
        login: TerminalAdminLogin,
        processor: EscalationReviewProcessor,
        audit_sink: AuditSink,
        input_reader: InputReader = input,
        output_writer: OutputWriter = print,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._login = login
        self._processor = processor
        self._audit_sink = audit_sink
        self._input_reader = input_reader
        self._output_writer = output_writer
        self._clock = clock

    def handle(self, *, state: CatalogAgentState) -> EscalationReviewResult:
        """Authenticate an escalator and record a bounded review."""
        escalation = state.escalation
        if escalation is None:
            return _escalation_rejection(
                state.request.request_id, "unavailable", "NO_CURRENT_ESCALATION"
            )
        self._output_writer(f"Escalation: {escalation.escalation_id}")
        self._output_writer(escalation.reason)
        self._output_writer(escalation.recommended_review)
        authentication = self._login.login(required_role=AdminRole.ESCALATOR)
        if authentication.status is not AuthenticationStatus.AUTHENTICATED:
            return _escalation_rejection(
                state.request.request_id,
                escalation.escalation_id,
                authentication.error_code or "AUTHENTICATION_REJECTED",
            )
        actor_id = authentication.actor_id
        if actor_id is None:
            return _escalation_rejection(
                state.request.request_id,
                escalation.escalation_id,
                "AUTHENTICATION_REJECTED",
            )
        self._output_writer("1. Acknowledge")
        self._output_writer("2. Reject")
        self._output_writer("3. Cancel")
        try:
            raw_decision = self._input_reader("Decision number: ").strip()
            decisions = {
                "1": EscalationDecision.ACKNOWLEDGE,
                "2": EscalationDecision.REJECT,
                "3": EscalationDecision.CANCEL,
            }
            decision = decisions.get(raw_decision)
            if decision is None:
                return self._rejected_after_authentication(
                    state, actor_id, "INVALID_ESCALATION_DECISION"
                )
            if decision is EscalationDecision.CANCEL:
                return self._rejected_after_authentication(
                    state,
                    actor_id,
                    "TERMINAL_INPUT_CANCELLED",
                    outcome="cancelled",
                )
            note = self._input_reader("Review note (optional): ").strip() or None
        except (EOFError, KeyboardInterrupt):
            return self._rejected_after_authentication(
                state, actor_id, "TERMINAL_INPUT_CANCELLED", outcome="cancelled"
            )
        if note is not None and len(note) > 1_000:
            return self._rejected_after_authentication(
                state, actor_id, "REVIEW_NOTE_TOO_LONG"
            )
        response = EscalationReviewResponse(
            request_id=state.request.request_id,
            escalation_id=escalation.escalation_id,
            reviewed_by=actor_id,
            decision=decision,
            review_note=note,
            submitted_at=self._clock(),
        )
        result = self._processor.apply(state=state, response=response)
        outcome = (
            "succeeded"
            if result.status is EscalationReviewStatus.APPLIED
            else "rejected"
        )
        self._record_event(state, actor_id, outcome)
        self._output_writer(
            "Escalation review recorded."
            if result.status is EscalationReviewStatus.APPLIED
            else "Escalation review rejected."
        )
        return result

    def _rejected_after_authentication(
        self,
        state: CatalogAgentState,
        actor_id: str,
        error_code: str,
        *,
        outcome: str = "rejected",
    ) -> EscalationReviewResult:
        self._record_event(state, actor_id, outcome)
        target_id = (
            state.escalation.escalation_id if state.escalation else "unavailable"
        )
        self._output_writer("Escalation review rejected.")
        return _escalation_rejection(state.request.request_id, target_id, error_code)

    def _record_event(
        self, state: CatalogAgentState, actor_id: str, outcome: str
    ) -> None:
        target_id = (
            state.escalation.escalation_id if state.escalation else "unavailable"
        )
        self._audit_sink.record(
            AdminAuditEvent(
                event_id=str(uuid4()),
                actor_id=actor_id,
                role=AdminRole.ESCALATOR,
                operation="review_escalation",
                request_id=state.request.request_id,
                target_id=target_id,
                outcome=outcome,
                occurred_at=self._clock(),
            )
        )


def _authentication_rejection(error_code: str) -> AuthenticationResult:
    return AuthenticationResult(
        status=AuthenticationStatus.REJECTED,
        message="Authentication failed.",
        error_code=error_code,
    )


def _clarification_rejection(
    request_id: str,
    clarification_id: str,
    error_code: str,
) -> ClarificationApplicationResult:
    return ClarificationApplicationResult(
        request_id=request_id,
        clarification_id=clarification_id,
        status=ClarificationApplicationStatus.REJECTED,
        changed=False,
        message="The clarification response was rejected.",
        error_code=error_code,
    )


def _escalation_rejection(
    request_id: str,
    escalation_id: str,
    error_code: str,
) -> EscalationReviewResult:
    return EscalationReviewResult(
        request_id=request_id,
        escalation_id=escalation_id,
        status=EscalationReviewStatus.REJECTED,
        changed=False,
        message="The escalation review was rejected.",
        error_code=error_code,
    )
