"""Tests for authenticated clarification and escalation terminal adapters."""

from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher

from project_catalog_agent.admin import (
    AdminAuthenticator,
    AdminCredential,
    AdminRole,
    EscalationDecision,
    EscalationReviewResponse,
    EscalationReviewStatus,
    InMemoryAuditSink,
)
from project_catalog_agent.admin.terminal import (
    TerminalAdminLogin,
    TerminalClarificationHandler,
    TerminalEscalationHandler,
)
from project_catalog_agent.agent import (
    CatalogStateUpdater,
    ClarificationResponseProcessor,
    EscalationReviewProcessor,
)
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ClarificationApplicationStatus,
    CreateProjectRequest,
    EscalationRequest,
)
from project_catalog_agent.taxonomy import JsonTaxonomyRepository
from tests.agent.test_clarification import pending_state

TEST_CLARIFIER_PASSWORD = "terminal-clarifier-password"
TEST_ESCALATOR_PASSWORD = "terminal-escalator-password"
NOW = datetime(2026, 1, 2, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def authenticator() -> AdminAuthenticator:
    """Build one test-only role-aware authenticator."""
    hasher = PasswordHasher(time_cost=1, memory_cost=8_192, parallelism=1)
    return AdminAuthenticator(
        credentials=(
            AdminCredential(
                username="clarifier",
                password_hash=hasher.hash(TEST_CLARIFIER_PASSWORD),
                role=AdminRole.CLARIFIER,
            ),
            AdminCredential(
                username="escalator",
                password_hash=hasher.hash(TEST_ESCALATOR_PASSWORD),
                role=AdminRole.ESCALATOR,
            ),
        ),
        password_hasher=hasher,
    )


def login(
    authenticator: AdminAuthenticator,
    username: str,
    password: str,
    outputs: list[str],
) -> TerminalAdminLogin:
    """Create a single-attempt deterministic login adapter."""
    return TerminalAdminLogin(
        authenticator=authenticator,
        max_attempts=1,
        input_reader=lambda _prompt: username,
        password_reader=lambda _prompt: password,
        output_writer=outputs.append,
    )


def clarification_handler(
    authenticator: AdminAuthenticator,
    *,
    username: str = "clarifier",
    password: str = TEST_CLARIFIER_PASSWORD,
    answer: str = "2",
) -> tuple[TerminalClarificationHandler, InMemoryAuditSink, list[str]]:
    """Build a fully controlled clarification terminal flow."""
    outputs: list[str] = []
    audit = InMemoryAuditSink()
    handler = TerminalClarificationHandler(
        login=login(authenticator, username, password, outputs),
        processor=ClarificationResponseProcessor(
            taxonomy_repository=JsonTaxonomyRepository(),
            state_updater=CatalogStateUpdater(),
            admin_authorizer=authenticator,
        ),
        audit_sink=audit,
        input_reader=lambda _prompt: answer,
        output_writer=outputs.append,
        clock=lambda: NOW,
    )
    return handler, audit, outputs


def escalation_state() -> CatalogAgentState:
    """Create a current escalation without a publishable completed profile."""
    request = CreateProjectRequest(
        request_id="ESC-001",
        project_name="Escalation Test",
        project_description="Human review is required.",
    )
    return CatalogAgentState(
        request=request,
        status=CatalogStatus.ESCALATED,
        stage=CatalogStage.ESCALATED,
        escalation=EscalationRequest(
            escalation_id="escalation-001",
            request_id=request.request_id,
            issue_code="MANUAL_REVIEW_REQUIRED",
            field="requirements[0]",
            reason="Automated recovery is unsafe.",
            context_summary="A blocking issue remains.",
            recommended_review="Review source evidence outside automation.",
        ),
        state_version=4,
    )


def escalation_handler(
    authenticator: AdminAuthenticator,
    *,
    username: str = "escalator",
    password: str = TEST_ESCALATOR_PASSWORD,
    inputs: tuple[str, ...] = ("1", "Reviewed safely."),
) -> tuple[TerminalEscalationHandler, InMemoryAuditSink, list[str]]:
    """Build a fully controlled escalation terminal flow."""
    values = iter(inputs)
    outputs: list[str] = []
    audit = InMemoryAuditSink()
    handler = TerminalEscalationHandler(
        login=login(authenticator, username, password, outputs),
        processor=EscalationReviewProcessor(
            state_updater=CatalogStateUpdater(),
            admin_authorizer=authenticator,
        ),
        audit_sink=audit,
        input_reader=lambda _prompt: next(values),
        output_writer=outputs.append,
        clock=lambda: NOW,
    )
    return handler, audit, outputs


def test_numbered_option_maps_to_value_and_records_safe_audit(
    authenticator: AdminAuthenticator,
) -> None:
    state = pending_state()
    before = state.model_dump_json()
    handler, audit, outputs = clarification_handler(authenticator)

    result = handler.handle(state=state)

    assert result.status is ClarificationApplicationStatus.APPLIED
    assert result.updated_state is not None
    assert result.updated_state.extraction_result is not None
    assert result.updated_state.extraction_result.requirements[0].required_level == 2
    assert result.updated_state.clarification_history[0].answered_by == "clarifier"
    assert state.model_dump_json() == before
    assert "Which verified value should be used?" in outputs
    assert [event.role for event in audit.events] == [AdminRole.CLARIFIER]
    assert audit.events[0].outcome == "succeeded"
    combined = "\n".join(outputs) + result.model_dump_json()
    assert TEST_CLARIFIER_PASSWORD not in combined
    assert "password_hash" not in combined


def test_escalator_cannot_answer_clarification_and_state_is_unchanged(
    authenticator: AdminAuthenticator,
) -> None:
    state = pending_state()
    before = state.model_dump_json()
    handler, audit, outputs = clarification_handler(
        authenticator,
        username="escalator",
        password=TEST_ESCALATOR_PASSWORD,
    )

    result = handler.handle(state=state)

    assert result.status is ClarificationApplicationStatus.REJECTED
    assert result.error_code == "MAX_AUTHENTICATION_ATTEMPTS"
    assert state.model_dump_json() == before
    assert audit.events == ()
    assert outputs[-1] == "Authentication failed."


def test_invalid_option_number_is_rejected_and_audited(
    authenticator: AdminAuthenticator,
) -> None:
    handler, audit, _outputs = clarification_handler(authenticator, answer="99")

    result = handler.handle(state=pending_state())

    assert result.error_code == "INVALID_SELECTED_OPTION"
    assert audit.events[0].outcome == "rejected"


def test_free_text_is_collected_only_when_pending_request_allows_it(
    authenticator: AdminAuthenticator,
) -> None:
    state = pending_state(
        issue_code="EVIDENCE_NOT_VERBATIM",
        field="requirements[0].evidence_text",
        options=[],
        allow_free_text=True,
    )
    outputs: list[str] = []
    audit = InMemoryAuditSink()
    handler = TerminalClarificationHandler(
        login=login(
            authenticator,
            "clarifier",
            TEST_CLARIFIER_PASSWORD,
            outputs,
        ),
        processor=ClarificationResponseProcessor(
            taxonomy_repository=JsonTaxonomyRepository(),
            state_updater=CatalogStateUpdater(),
            admin_authorizer=authenticator,
        ),
        audit_sink=audit,
        input_reader=lambda _prompt: "Exact verified evidence.",
        output_writer=outputs.append,
        clock=lambda: NOW,
    )

    result = handler.handle(state=state)

    assert result.status is ClarificationApplicationStatus.APPLIED
    assert result.updated_state is not None
    assert result.updated_state.extraction_result is not None
    assert (
        result.updated_state.extraction_result.requirements[0].evidence_text
        == "Exact verified evidence."
    )
    assert audit.events[0].outcome == "succeeded"


def test_escalation_acknowledgement_records_review_without_completion(
    authenticator: AdminAuthenticator,
) -> None:
    state = escalation_state()
    handler, audit, outputs = escalation_handler(authenticator)

    result = handler.handle(state=state)

    assert result.status is EscalationReviewStatus.APPLIED
    assert result.updated_state is not None
    updated = result.updated_state
    assert updated.status is CatalogStatus.ESCALATED
    assert updated.stage is CatalogStage.ESCALATED
    assert updated.state_version == state.state_version + 1
    assert updated.escalation_review_history[0].reviewed_by == "escalator"
    assert updated.escalation_review_history[0].decision == "acknowledge"
    assert audit.events[0].role is AdminRole.ESCALATOR
    assert audit.events[0].outcome == "succeeded"
    assert TEST_ESCALATOR_PASSWORD not in "\n".join(outputs)


def test_clarifier_cannot_review_escalation_and_state_is_unchanged(
    authenticator: AdminAuthenticator,
) -> None:
    state = escalation_state()
    before = state.model_dump_json()
    handler, audit, _outputs = escalation_handler(
        authenticator,
        username="clarifier",
        password=TEST_CLARIFIER_PASSWORD,
    )

    result = handler.handle(state=state)

    assert result.status is EscalationReviewStatus.REJECTED
    assert state.model_dump_json() == before
    assert audit.events == ()


def test_replayed_escalation_review_is_rejected(
    authenticator: AdminAuthenticator,
) -> None:
    state = escalation_state()
    processor = EscalationReviewProcessor(
        state_updater=CatalogStateUpdater(), admin_authorizer=authenticator
    )
    response = EscalationReviewResponse(
        request_id="ESC-001",
        escalation_id="escalation-001",
        reviewed_by="escalator",
        decision=EscalationDecision.ACKNOWLEDGE,
        submitted_at=NOW,
    )
    first = processor.apply(state=state, response=response)
    assert first.updated_state is not None

    replay = processor.apply(state=first.updated_state, response=response)

    assert replay.error_code == "ESCALATION_ALREADY_REVIEWED"


def test_wrong_escalation_id_is_rejected(
    authenticator: AdminAuthenticator,
) -> None:
    response = EscalationReviewResponse(
        request_id="ESC-001",
        escalation_id="wrong",
        reviewed_by="escalator",
        decision=EscalationDecision.REJECT,
        submitted_at=NOW,
    )
    result = EscalationReviewProcessor(
        state_updater=CatalogStateUpdater(), admin_authorizer=authenticator
    ).apply(state=escalation_state(), response=response)

    assert result.error_code == "ESCALATION_ID_MISMATCH"


def test_review_note_length_is_enforced_and_audited(
    authenticator: AdminAuthenticator,
) -> None:
    handler, audit, _outputs = escalation_handler(
        authenticator, inputs=("1", "x" * 1_001)
    )

    result = handler.handle(state=escalation_state())

    assert result.error_code == "REVIEW_NOTE_TOO_LONG"
    assert audit.events[0].outcome == "rejected"
