"""Injected transcript tests for the complete controlled terminal demo."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher

from project_catalog_agent.catalog.contracts import CatalogStage, CatalogStatus
from project_catalog_agent.demo import DemoScenario
from project_catalog_agent.persistence import (
    ProjectRepositoryError,
    StoredProject,
)
from project_catalog_agent.terminal_demo import TerminalDemoApplication, parse_arguments

CLARIFIER_PASSWORD = "demo-test-clarifier-password"
ESCALATOR_PASSWORD = "demo-test-escalator-password"
NOW = datetime(2026, 2, 1, 12, tzinfo=UTC)
_HASHER = PasswordHasher(time_cost=1, memory_cost=8_192, parallelism=1)
CLARIFIER_HASH = _HASHER.hash(CLARIFIER_PASSWORD)
ESCALATOR_HASH = _HASHER.hash(ESCALATOR_PASSWORD)


@pytest.fixture(autouse=True)
def configured_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure runtime-generated test-only hashes for each transcript."""
    monkeypatch.setenv("CLARIFIER_USERNAME", "clarifier")
    monkeypatch.setenv("CLARIFIER_PASSWORD_HASH", CLARIFIER_HASH)
    monkeypatch.setenv("ESCALATOR_USERNAME", "escalator")
    monkeypatch.setenv("ESCALATOR_PASSWORD_HASH", ESCALATOR_HASH)


def application(
    inputs: list[str],
    *,
    password: str = CLARIFIER_PASSWORD,
    max_transitions: int = 20,
    show_state: bool = False,
    project_repository: object | None = None,
) -> tuple[TerminalDemoApplication, list[str], list[str]]:
    """Create a deterministic app and captured terminal streams."""
    values: Iterator[str] = iter(inputs)
    output: list[str] = []
    password_prompts: list[str] = []
    application_options: dict[str, object] = {}
    if project_repository is not None:
        application_options["project_repository"] = project_repository
    app = TerminalDemoApplication(
        input_reader=lambda _prompt: next(values),
        password_reader=lambda prompt: (
            password_prompts.append(prompt),
            password,
        )[1],
        output_writer=output.append,
        clock=lambda: NOW,
        id_generator=lambda: "CONTROLLED-ID",
        max_transitions=max_transitions,
        show_state=show_state,
        **application_options,
    )
    return app, output, password_prompts


def run(app: TerminalDemoApplication, scenario: DemoScenario | None) -> None:
    """Run one async app transcript."""
    assert asyncio.run(app.run(scenario)) == 0


def test_ambiguous_cloud_clarification_resumes_and_completes() -> None:
    app, output, password_prompts = application(["y", "clarifier", "1"])

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.COMPLETED
    assert app.last_state.stage is CatalogStage.COMPLETED
    assert app.last_state.candidate_profile is not None
    assert [
        requirement.skill_id
        for requirement in app.last_state.candidate_profile.requirements
    ] == ["python", "aws"]
    transcript = "\n".join(output)
    assert "Which taxonomy skill best represents" in transcript
    assert "Clarifications applied: 1" in transcript
    assert "AWS | preferred | 1" in transcript
    assert CLARIFIER_PASSWORD not in transcript
    assert password_prompts == ["Password: "]


def test_missing_level_clarification_selects_level_two_and_completes() -> None:
    app, output, _ = application(["y", "clarifier", "2"])

    run(app, DemoScenario.MISSING_LEVEL)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.COMPLETED
    assert app.last_state.extraction_result is not None
    assert app.last_state.extraction_result.requirements[0].required_level == 2
    assert "Python | hard_requirement | 2" in "\n".join(output)


def test_clarifier_is_rejected_at_escalation_gate_without_state_change() -> None:
    app, output, _ = application(
        ["y", "clarifier", "clarifier", "clarifier"],
        password=CLARIFIER_PASSWORD,
    )

    run(app, DemoScenario.UNMAPPED_SKILL)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.ESCALATED
    assert app.last_state.escalation_review_history == []
    assert output.count("Authentication failed.") == 3
    assert "Escalations reviewed: 0" in output


def test_escalator_acknowledges_without_completing_or_publishing() -> None:
    app, output, _ = application(
        ["y", "escalator", "1", "Send for taxonomy governance."],
        password=ESCALATOR_PASSWORD,
    )

    run(app, DemoScenario.UNMAPPED_SKILL)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.ESCALATED
    assert len(app.last_state.escalation_review_history) == 1
    transcript = "\n".join(output)
    assert "Project was not completed or published." in transcript
    assert "review_escalation" in transcript
    assert ESCALATOR_PASSWORD not in transcript


def test_wrong_password_stops_after_three_attempts() -> None:
    app, output, _ = application(
        ["y", "clarifier", "clarifier", "clarifier"],
        password="wrong-test-password",
    )

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.AWAITING_CLARIFICATION
    assert app.last_state.pending_clarification is not None
    assert output.count("Authentication failed.") == 3
    assert "State was not modified." in output
    assert "wrong-test-password" not in "\n".join(output)


def test_cancel_clarification_preserves_pending_state() -> None:
    app, output, password_prompts = application(["n"])

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.AWAITING_CLARIFICATION
    assert app.last_state.pending_clarification is not None
    assert app.last_state.clarification_history == []
    assert password_prompts == []
    assert "Clarifications applied: 0" in output


def test_authenticated_clarification_cancel_preserves_pending_state() -> None:
    app, output, _ = application(["y", "clarifier", "3"])

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.AWAITING_CLARIFICATION
    assert app.last_state.pending_clarification is not None
    assert app.last_state.clarification_history == []
    assert "State was not modified." in output


def test_keyboard_interrupt_during_password_is_clean_cancellation() -> None:
    values = iter(["y", "clarifier"])
    output: list[str] = []

    def cancelled_password(_prompt: str) -> str:
        raise KeyboardInterrupt

    app = TerminalDemoApplication(
        input_reader=lambda _prompt: next(values),
        password_reader=cancelled_password,
        output_writer=output.append,
        clock=lambda: NOW,
    )

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.AWAITING_CLARIFICATION
    assert "Authentication cancelled." in output
    assert "State was not modified." in output


def test_invalid_main_menu_input_recovers_and_renders_menu() -> None:
    app, output, _ = application(["not-a-choice", "7"])

    run(app, None)

    assert "Project Catalog Agent — Interactive Terminal Demo" in output
    assert "Invalid selection. Please enter one listed option." in output
    assert output[-1] == "Demo closed."


def test_maximum_transition_limit_stops_safely() -> None:
    app, output, _ = application([], max_transitions=1)

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.stage is CatalogStage.EXTRACTED
    assert "Maximum transition limit reached; processing stopped." in output


def test_exhausted_recovery_records_no_progress_then_escalates() -> None:
    app, output, _ = application(["n"])

    run(app, DemoScenario.EXHAUSTED_RECOVERY)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.ESCALATED
    assert [
        entry.action_request.action.value for entry in app.last_state.recovery_history
    ] == ["reconsider_mapping", "escalate"]
    assert "Recovery attempts: 2" in output


def test_custom_valid_project_uses_generated_request_id_and_completes() -> None:
    app, output, _ = application(
        ["Custom Project", "Build a useful service.", "n", "1"]
    )

    run(app, DemoScenario.CUSTOM)

    assert app.last_state is not None
    assert app.last_state.request.request_id == "DEMO-CONTROLLED-ID"
    assert app.last_state.status is CatalogStatus.COMPLETED
    assert "Mode: controlled demonstration" in output


def test_exact_rerun_reports_already_published_with_same_project_id() -> None:
    app, output, _ = application(["y", "clarifier", "1", "y", "clarifier", "1"])

    run(app, DemoScenario.AMBIGUOUS_CLOUD)
    first_project_id = app.last_state.published_project_id if app.last_state else None
    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert first_project_id == "PRJ-CONTROLLED-ID"
    assert app.last_state is not None
    assert app.last_state.published_project_id == first_project_id
    assert "Publication status: already_published" in output
    assert "Existing project ID: PRJ-CONTROLLED-ID" in output


class _FailingProjectRepository:
    def create(self, project: StoredProject) -> StoredProject:
        del project
        raise ProjectRepositoryError("sensitive database detail")

    def get_by_request_id(self, request_id: str) -> StoredProject | None:
        del request_id
        return None

    def get_by_project_id(self, project_id: str) -> StoredProject | None:
        del project_id
        return None

    def list_projects(self) -> tuple[StoredProject, ...]:
        return ()


def test_repository_failure_is_displayed_without_internal_details() -> None:
    app, output, _ = application(
        ["y", "clarifier", "1"],
        project_repository=_FailingProjectRepository(),
    )

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.PROCESSING
    transcript = "\n".join(output)
    assert "Publication status: failed" in transcript
    assert "Reason: REPOSITORY_FAILURE" in transcript
    assert "sensitive database detail" not in transcript


def test_missing_credentials_stop_before_protected_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLARIFIER_PASSWORD_HASH", "")
    monkeypatch.setenv("ESCALATOR_PASSWORD_HASH", "")
    app, output, password_prompts = application(["y"])

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.AWAITING_CLARIFICATION
    assert "Admin credentials are not configured." in output
    assert "  python -m project_catalog_agent.admin_setup" in output
    assert password_prompts == []


def test_escalation_cancel_does_not_append_review_history() -> None:
    app, output, _ = application(["y", "escalator", "3"], password=ESCALATOR_PASSWORD)

    run(app, DemoScenario.UNMAPPED_SKILL)

    assert app.last_state is not None
    assert app.last_state.status is CatalogStatus.ESCALATED
    assert app.last_state.escalation_review_history == []
    assert "State was not modified." in output


def test_show_state_output_contains_no_credential_material() -> None:
    app, output, _ = application(["n"], show_state=True)

    run(app, DemoScenario.AMBIGUOUS_CLOUD)

    transcript = "\n".join(output).casefold()
    assert CLARIFIER_PASSWORD.casefold() not in transcript
    assert CLARIFIER_HASH.casefold() not in transcript
    assert "password_hash" not in transcript


def test_cli_rejects_password_options() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["--password", "not-accepted"])
