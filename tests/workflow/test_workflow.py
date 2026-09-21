"""End-to-end tests for resumable LangGraph catalog orchestration."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from project_catalog_agent.catalog.contracts import (
    CatalogStage,
    CatalogStatus,
    ClarificationResponse,
    CreateProjectRequest,
    DecisionType,
)
from project_catalog_agent.demo import DemoScenario
from project_catalog_agent.demo.scenarios import scenario_bundle
from project_catalog_agent.persistence import (
    InMemoryProjectRepository,
    ProjectRepositoryError,
    StoredProject,
)
from project_catalog_agent.workflow import (
    CatalogWorkflowConfig,
    InMemoryWorkflowEventSink,
    WorkflowNotAwaitingClarificationError,
    WorkflowOutcome,
    WorkflowThreadMismatchError,
    create_controlled_workflow,
    create_memory_checkpointer,
    decision_routes,
    open_async_sqlite_checkpointer,
)
from tests.workflow.helpers import NOW, ControlledAuthorizer, workflow_for_bundle


def run_async_test(
    function: Callable[[], Coroutine[Any, Any, None]],
) -> Callable[[], None]:
    """Run one zero-argument async scenario without an asyncio test plugin."""

    @wraps(function)
    def wrapped() -> None:
        asyncio.run(function())

    return wrapped


@run_async_test
async def test_happy_path_publishes_and_checkpoints_complete_state() -> None:
    request = CreateProjectRequest(
        request_id="E2E-001",
        project_name="Python Reporting Application",
        project_description="Build a reporting application using Python.",
    )
    workflow, repository, events = workflow_for_bundle(
        scenario_bundle(DemoScenario.CUSTOM, request=request)
    )

    result = await workflow.start(request)

    assert result.outcome is WorkflowOutcome.COMPLETED
    assert result.catalog_state.status is CatalogStatus.COMPLETED
    assert result.catalog_state.stage is CatalogStage.COMPLETED
    assert result.stored_project_id == "PRJ-WORKFLOW-001"
    assert repository.get_by_project_id("PRJ-WORKFLOW-001") is not None
    restored = await workflow.get_state(thread_id=request.request_id)
    assert restored == result.catalog_state
    assert [event.event for event in events.events][-1] == "workflow_completed"


@run_async_test
async def test_clarification_interrupt_is_safe_and_resumes_same_thread() -> None:
    bundle = scenario_bundle(DemoScenario.AMBIGUOUS_CLOUD)
    workflow, repository, events = workflow_for_bundle(bundle)

    paused = await workflow.start(bundle.request)

    assert paused.outcome is WorkflowOutcome.AWAITING_CLARIFICATION
    assert paused.pending_clarification is not None
    serialized = paused.model_dump_json().casefold()
    for forbidden in ("password", "password_hash", "token", "authorization"):
        assert forbidden not in serialized
    option = paused.pending_clarification.options[0]
    resumed = await workflow.resume_clarification(
        thread_id=paused.thread_id,
        response=ClarificationResponse(
            request_id=paused.request_id,
            clarification_id=paused.pending_clarification.clarification_id,
            answered_by="clarifier",
            selected_value=option.value,
            submitted_at=datetime(2026, 4, 1, 13, tzinfo=UTC),
        ),
    )

    assert resumed.outcome is WorkflowOutcome.COMPLETED
    assert len(repository.list_projects()) == 1
    assert "clarification_requested" in [event.event for event in events.events]
    assert "clarification_applied" in [event.event for event in events.events]
    with pytest.raises(WorkflowNotAwaitingClarificationError):
        await workflow.resume_clarification(
            thread_id=paused.thread_id,
            response=ClarificationResponse(
                request_id=paused.request_id,
                clarification_id=paused.pending_clarification.clarification_id,
                answered_by="clarifier",
                selected_value=option.value,
                submitted_at=datetime(2026, 4, 1, 14, tzinfo=UTC),
            ),
        )


@run_async_test
async def test_wrong_clarification_id_is_rejected_and_remains_paused() -> None:
    bundle = scenario_bundle(DemoScenario.AMBIGUOUS_CLOUD)
    workflow, _, _ = workflow_for_bundle(bundle)
    paused = await workflow.start(bundle.request)
    assert paused.pending_clarification is not None

    result = await workflow.resume_clarification(
        thread_id=paused.thread_id,
        response=ClarificationResponse(
            request_id=paused.request_id,
            clarification_id="wrong-id",
            answered_by="clarifier",
            selected_value=paused.pending_clarification.options[0].value,
            submitted_at=datetime(2026, 4, 1, 13, tzinfo=UTC),
        ),
    )

    assert result.outcome is WorkflowOutcome.AWAITING_CLARIFICATION
    assert result.error is not None
    assert result.error.code == "CLARIFICATION_ID_MISMATCH"


@run_async_test
async def test_mismatched_resume_thread_is_rejected_before_graph_resume() -> None:
    bundle = scenario_bundle(DemoScenario.AMBIGUOUS_CLOUD)
    workflow, _, _ = workflow_for_bundle(bundle)
    paused = await workflow.start(bundle.request)
    assert paused.pending_clarification is not None

    with pytest.raises(WorkflowThreadMismatchError):
        await workflow.resume_clarification(
            thread_id=paused.thread_id,
            response=ClarificationResponse(
                request_id="DIFFERENT-REQUEST",
                clarification_id=paused.pending_clarification.clarification_id,
                answered_by="clarifier",
                selected_value=paused.pending_clarification.options[0].value,
                submitted_at=datetime(2026, 4, 1, 13, tzinfo=UTC),
            ),
        )


@run_async_test
async def test_unmapped_skill_escalates_without_publication() -> None:
    bundle = scenario_bundle(DemoScenario.UNMAPPED_SKILL)
    workflow, repository, events = workflow_for_bundle(bundle)

    result = await workflow.start(bundle.request)

    assert result.outcome is WorkflowOutcome.ESCALATED
    assert result.escalation is not None
    assert repository.list_projects() == ()
    assert "workflow_escalated" in [event.event for event in events.events]


@run_async_test
async def test_completed_start_is_request_idempotent() -> None:
    request = CreateProjectRequest(
        request_id="E2E-004",
        project_name="Retry",
        project_description="Build using Python.",
    )
    workflow, repository, _ = workflow_for_bundle(
        scenario_bundle(DemoScenario.CUSTOM, request=request)
    )
    first = await workflow.start(request)

    second = await workflow.start(request)

    assert second.outcome is WorkflowOutcome.COMPLETED
    assert second.stored_project_id == first.stored_project_id
    assert len(repository.list_projects()) == 1


@run_async_test
async def test_publication_retry_with_fresh_checkpoint_is_idempotent() -> None:
    request = CreateProjectRequest(
        request_id="E2E-004-FRESH",
        project_name="Retry",
        project_description="Build using Python.",
    )
    bundle = scenario_bundle(DemoScenario.CUSTOM, request=request)
    repository = InMemoryProjectRepository()
    first = create_controlled_workflow(
        bundle=bundle,
        repository=repository,
        checkpointer=create_memory_checkpointer(),
        admin_authorizer=ControlledAuthorizer(),
        project_id_factory=lambda: "PRJ-ORIGINAL",
    )
    await first.start(request)
    retry_events = InMemoryWorkflowEventSink()
    retry = create_controlled_workflow(
        bundle=bundle,
        repository=repository,
        checkpointer=create_memory_checkpointer(),
        admin_authorizer=ControlledAuthorizer(),
        event_sink=retry_events,
        project_id_factory=lambda: (_ for _ in ()).throw(
            AssertionError("ID factory must not run on exact retry")
        ),
    )

    result = await retry.start(request)

    assert result.outcome is WorkflowOutcome.COMPLETED
    assert result.stored_project_id == "PRJ-ORIGINAL"
    assert len(repository.list_projects()) == 1
    assert "publication_idempotent" in [event.event for event in retry_events.events]


@run_async_test
async def test_different_thread_ids_are_checkpoint_isolated() -> None:
    first_request = CreateProjectRequest(
        request_id="THREAD-ONE",
        project_name="First",
        project_description="Build using Python.",
    )
    second_request = first_request.model_copy(
        update={"request_id": "THREAD-TWO", "project_name": "Second"}
    )
    ids = iter(["PRJ-ONE", "PRJ-TWO"])
    workflow, repository, _ = workflow_for_bundle(
        scenario_bundle(DemoScenario.CUSTOM, request=first_request),
        project_id_factory=lambda: next(ids),
    )

    first = await workflow.start(first_request)
    second = await workflow.start(second_request)

    assert first.stored_project_id == "PRJ-ONE"
    assert second.stored_project_id == "PRJ-TWO"
    assert (await workflow.get_state(thread_id="THREAD-ONE")).request == first_request
    assert (await workflow.get_state(thread_id="THREAD-TWO")).request == second_request
    assert len(repository.list_projects()) == 2


@run_async_test
async def test_sqlite_checkpoint_restores_completed_workflow() -> None:
    temporary_directory = TemporaryDirectory()
    path = Path(temporary_directory.name) / "workflow-checkpoints.sqlite3"
    request = CreateProjectRequest(
        request_id="SQLITE-WORKFLOW",
        project_name="Durable",
        project_description="Build using Python.",
    )
    bundle = scenario_bundle(DemoScenario.CUSTOM, request=request)
    repository = InMemoryProjectRepository()
    async with open_async_sqlite_checkpointer(path) as checkpointer:
        workflow = create_controlled_workflow(
            bundle=bundle,
            repository=repository,
            checkpointer=checkpointer,
            admin_authorizer=ControlledAuthorizer(),
            config=CatalogWorkflowConfig(),
            clock=lambda: NOW,
            project_id_factory=lambda: "PRJ-SQLITE",
        )
        first = await workflow.start(request)
    async with open_async_sqlite_checkpointer(path) as checkpointer:
        restored_workflow = create_controlled_workflow(
            bundle=bundle,
            repository=repository,
            checkpointer=checkpointer,
            admin_authorizer=ControlledAuthorizer(),
            clock=lambda: NOW,
            project_id_factory=lambda: "SHOULD-NOT-BE-CALLED",
        )
        restored = await restored_workflow.start(request)

    assert first.outcome is WorkflowOutcome.COMPLETED
    assert restored.catalog_state == first.catalog_state
    assert len(repository.list_projects()) == 1
    raw_checkpoint = path.read_bytes().lower()
    for forbidden in (b"password", b"password_hash", b"authorization"):
        assert forbidden not in raw_checkpoint
    temporary_directory.cleanup()


class _FailingRepository:
    def create(self, project: StoredProject) -> StoredProject:
        del project
        raise ProjectRepositoryError("private database detail")

    def get_by_request_id(self, request_id: str) -> StoredProject | None:
        del request_id
        return None

    def get_by_project_id(self, project_id: str) -> StoredProject | None:
        del project_id
        return None

    def list_projects(self) -> tuple[StoredProject, ...]:
        return ()


@run_async_test
async def test_repository_failure_is_safe_and_never_completes() -> None:
    request = CreateProjectRequest(
        request_id="E2E-005",
        project_name="Failure",
        project_description="Build using Python.",
    )
    workflow, _, _ = workflow_for_bundle(
        scenario_bundle(DemoScenario.CUSTOM, request=request),
        repository=_FailingRepository(),
    )

    result = await workflow.start(request)

    assert result.outcome is WorkflowOutcome.PERMANENT_FAILURE
    assert result.catalog_state.status is CatalogStatus.PERMANENT_FAILURE
    assert result.catalog_state.published_project_id is None
    assert result.error is not None
    assert result.error.code == "REPOSITORY_FAILURE"
    assert "private database detail" not in result.model_dump_json()


@run_async_test
async def test_transition_limit_terminates_before_publication() -> None:
    request = CreateProjectRequest(
        request_id="E2E-006",
        project_name="Limit",
        project_description="Build using Python.",
    )
    workflow, repository, _ = workflow_for_bundle(
        scenario_bundle(DemoScenario.CUSTOM, request=request),
        max_transitions=2,
    )

    result = await workflow.start(request)

    assert result.outcome is WorkflowOutcome.PERMANENT_FAILURE
    assert result.error is not None
    assert result.error.code == "TRANSITION_LIMIT_REACHED"
    assert repository.list_projects() == ()


def test_every_decision_type_has_one_route() -> None:
    routes = decision_routes()

    assert set(routes) == set(DecisionType)
    assert len(set(routes.values())) == len(routes)


@run_async_test
async def test_checkpoint_and_events_are_secret_free_json() -> None:
    bundle = scenario_bundle(DemoScenario.AMBIGUOUS_CLOUD)
    workflow, _, events = workflow_for_bundle(bundle)
    result = await workflow.start(bundle.request)

    checkpoint_view = json.dumps(result.model_dump(mode="json")).casefold()
    event_view = json.dumps(
        [event.model_dump(mode="json") for event in events.events]
    ).casefold()
    for forbidden in ("password", "password_hash", "token", "secret"):
        assert forbidden not in checkpoint_view
        assert forbidden not in event_view
