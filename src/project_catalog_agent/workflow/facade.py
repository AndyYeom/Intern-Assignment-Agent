"""Application-facing facade over LangGraph invocation and checkpoints."""

from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStatus,
    ClarificationResponse,
    CreateProjectRequest,
    create_initial_catalog_state,
)
from project_catalog_agent.workflow.contracts import (
    CatalogWorkflowResult,
    CatalogWorkflowState,
    WorkflowError,
    WorkflowOutcome,
)
from project_catalog_agent.workflow.errors import (
    WorkflowNotAwaitingClarificationError,
    WorkflowNotFoundError,
    WorkflowThreadMismatchError,
)
from project_catalog_agent.workflow.events import (
    EventSink,
    WorkflowEvent,
    discard_workflow_event,
)
from project_catalog_agent.workflow.graph import WorkflowGraph


class CatalogWorkflow:
    """Start, resume, and inspect one checkpointed catalog workflow."""

    def __init__(
        self,
        *,
        graph: WorkflowGraph,
        event_sink: EventSink = discard_workflow_event,
        recursion_limit: int = 100,
    ) -> None:
        if recursion_limit < 1:
            raise ValueError("recursion_limit must be positive")
        self._graph = graph
        self._event_sink = event_sink
        self._recursion_limit = recursion_limit

    async def start(self, request: CreateProjectRequest) -> CatalogWorkflowResult:
        """Start a new request or intentionally return its existing checkpoint."""
        validated = CreateProjectRequest.model_validate(request.model_dump())
        thread_id = validated.request_id
        config = self._config(thread_id)
        snapshot = await self._graph.aget_state(config)
        if snapshot.values:
            state = self._workflow_state(snapshot.values)
            self._assert_thread_request(thread_id, state["catalog_state"])
            return self._result(thread_id, state)

        initial: CatalogWorkflowState = {
            "catalog_state": create_initial_catalog_state(validated),
            "last_decision": None,
            "last_publication_result": None,
            "transition_count": 0,
            "workflow_error": None,
        }
        self._event_sink(
            WorkflowEvent(
                event="workflow_started",
                request_id=validated.request_id,
                thread_id=thread_id,
                state_version=1,
                transition_count=0,
            )
        )
        await self._graph.ainvoke(initial, config)
        return await self._result_from_checkpoint(thread_id)

    async def resume_clarification(
        self,
        *,
        thread_id: str,
        response: ClarificationResponse,
    ) -> CatalogWorkflowResult:
        """Resume the exact interrupted thread with credential-free trusted input."""
        normalized_thread_id = thread_id.strip()
        if not normalized_thread_id:
            raise ValueError("thread_id is required")
        validated = ClarificationResponse.model_validate(response.model_dump())
        config = self._config(normalized_thread_id)
        snapshot = await self._graph.aget_state(config)
        if not snapshot.values:
            raise WorkflowNotFoundError("workflow checkpoint was not found")
        state = self._workflow_state(snapshot.values)
        self._assert_thread_request(normalized_thread_id, state["catalog_state"])
        if validated.request_id != normalized_thread_id:
            raise WorkflowThreadMismatchError(
                "clarification response does not match the workflow thread"
            )
        if "await_clarification" not in snapshot.next:
            raise WorkflowNotAwaitingClarificationError(
                "workflow is not awaiting clarification"
            )
        await self._graph.ainvoke(
            Command(resume=validated.model_dump(mode="json")),
            config,
        )
        return await self._result_from_checkpoint(normalized_thread_id)

    async def get_state(self, *, thread_id: str) -> CatalogAgentState:
        """Return a detached authoritative catalog state from a checkpoint."""
        normalized_thread_id = thread_id.strip()
        snapshot = await self._graph.aget_state(self._config(normalized_thread_id))
        if not snapshot.values:
            raise WorkflowNotFoundError("workflow checkpoint was not found")
        state = self._workflow_state(snapshot.values)
        self._assert_thread_request(normalized_thread_id, state["catalog_state"])
        return state["catalog_state"].model_copy(deep=True)

    async def record_escalation_review(
        self,
        *,
        thread_id: str,
        updated_state: CatalogAgentState,
    ) -> None:
        """Checkpoint an already-authorized review without resuming automation."""
        normalized_thread_id = thread_id.strip()
        snapshot = await self._graph.aget_state(self._config(normalized_thread_id))
        if not snapshot.values:
            raise WorkflowNotFoundError("workflow checkpoint was not found")
        current = self._workflow_state(snapshot.values)["catalog_state"]
        self._assert_thread_request(normalized_thread_id, current)
        self._assert_thread_request(normalized_thread_id, updated_state)
        if (
            current.status is not CatalogStatus.ESCALATED
            or updated_state.status is not CatalogStatus.ESCALATED
            or updated_state.escalation is None
            or len(updated_state.escalation_review_history)
            != len(current.escalation_review_history) + 1
        ):
            raise ValueError("only one bounded escalation review may be recorded")
        await self._graph.aupdate_state(
            self._config(normalized_thread_id),
            {"catalog_state": updated_state},
            as_node="terminal_escalated",
        )

    async def _result_from_checkpoint(self, thread_id: str) -> CatalogWorkflowResult:
        snapshot = await self._graph.aget_state(self._config(thread_id))
        if not snapshot.values:
            raise WorkflowNotFoundError("workflow checkpoint was not found")
        return self._result(thread_id, self._workflow_state(snapshot.values))

    @staticmethod
    def _workflow_state(values: object) -> CatalogWorkflowState:
        raw = cast(dict[str, object], values)
        return CatalogWorkflowState(
            catalog_state=CatalogAgentState.model_validate(raw["catalog_state"]),
            last_decision=raw.get("last_decision"),  # type: ignore[typeddict-item]
            last_publication_result=raw.get(  # type: ignore[typeddict-item]
                "last_publication_result"
            ),
            transition_count=int(cast(int, raw.get("transition_count", 0))),
            workflow_error=raw.get("workflow_error"),  # type: ignore[typeddict-item]
        )

    @staticmethod
    def _assert_thread_request(
        thread_id: str,
        state: CatalogAgentState,
    ) -> None:
        if state.request.request_id != thread_id:
            raise WorkflowThreadMismatchError(
                "workflow thread belongs to a different request"
            )

    def _config(self, thread_id: str) -> RunnableConfig:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self._recursion_limit,
        }

    @staticmethod
    def _result(
        thread_id: str,
        workflow_state: CatalogWorkflowState,
    ) -> CatalogWorkflowResult:
        state = workflow_state["catalog_state"]
        common: dict[str, object] = {
            "request_id": state.request.request_id,
            "thread_id": thread_id,
            "catalog_state": state.model_copy(deep=True),
            "error": workflow_state.get("workflow_error"),
        }
        if state.status is CatalogStatus.COMPLETED:
            return CatalogWorkflowResult(
                **common,
                outcome=WorkflowOutcome.COMPLETED,
                stored_project_id=state.published_project_id,
            )
        if state.status is CatalogStatus.AWAITING_CLARIFICATION:
            return CatalogWorkflowResult(
                **common,
                outcome=WorkflowOutcome.AWAITING_CLARIFICATION,
                pending_clarification=state.pending_clarification,
            )
        if state.status is CatalogStatus.ESCALATED:
            return CatalogWorkflowResult(
                **common,
                outcome=WorkflowOutcome.ESCALATED,
                escalation=state.escalation,
            )
        error = workflow_state.get("workflow_error") or WorkflowError(
            code="STATE_UPDATE_FAILED",
            message="The workflow stopped outside a supported terminal state.",
            node="facade",
            retryable=False,
        )
        return CatalogWorkflowResult(
            **{**common, "error": error},
            outcome=WorkflowOutcome.PERMANENT_FAILURE,
        )
