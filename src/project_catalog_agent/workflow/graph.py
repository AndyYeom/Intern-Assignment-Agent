"""LangGraph topology for resumable, deterministically controlled catalog work."""

from contextlib import suppress
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    AgentError,
    CatalogStage,
    CatalogStatus,
    ClarificationApplicationStatus,
    ClarificationResponse,
    DecisionType,
    RecoveryContext,
)
from project_catalog_agent.persistence import PublicationStatus
from project_catalog_agent.workflow.contracts import (
    CatalogWorkflowConfig,
    CatalogWorkflowState,
    WorkflowError,
)
from project_catalog_agent.workflow.events import (
    EventSink,
    WorkflowEvent,
    discard_workflow_event,
)
from project_catalog_agent.workflow.services import CatalogWorkflowServices

WorkflowGraph = CompiledStateGraph[
    CatalogWorkflowState,
    None,
    CatalogWorkflowState,
    CatalogWorkflowState,
]

_ROUTES: dict[DecisionType, str] = {
    DecisionType.RUN_EXTRACTION: "extract",
    DecisionType.RUN_NORMALIZATION: "normalize",
    DecisionType.BUILD_PROFILE: "build_profile",
    DecisionType.RUN_VALIDATION: "validate",
    DecisionType.EXECUTE_RECOVERY: "execute_recovery",
    DecisionType.WAIT_FOR_CLARIFICATION: "await_clarification",
    DecisionType.PUBLISH_PROFILE: "publish",
    DecisionType.COMPLETE: "terminal_success",
    DecisionType.STOP_ESCALATED: "terminal_escalated",
    DecisionType.STOP_PERMANENT_FAILURE: "permanent_failure",
}
_OPERATIONAL_ROUTES = {
    "extract",
    "normalize",
    "build_profile",
    "validate",
    "execute_recovery",
    "await_clarification",
    "publish",
}


def decision_routes() -> dict[DecisionType, str]:
    """Return a copy of the exhaustive deterministic decision route table."""
    return dict(_ROUTES)


def build_catalog_workflow_graph(
    *,
    services: CatalogWorkflowServices,
    checkpointer: BaseCheckpointSaver[str],
    workflow_config: CatalogWorkflowConfig | None = None,
    event_sink: EventSink = discard_workflow_event,
) -> WorkflowGraph:
    """Compile the complete workflow with injected runtime-only dependencies."""
    safety = workflow_config or CatalogWorkflowConfig()

    def emit(
        name: str,
        state: CatalogWorkflowState,
        config: RunnableConfig,
        *,
        node: str | None = None,
        outcome: str | None = None,
        project_id: str | None = None,
    ) -> None:
        catalog_state = state["catalog_state"]
        decision = state.get("last_decision")
        action = getattr(decision, "action_request", None)
        raw_decision_type = getattr(decision, "decision_type", None)
        decision_type = getattr(raw_decision_type, "value", None)
        event_sink(
            WorkflowEvent(
                event=name,
                request_id=catalog_state.request.request_id,
                thread_id=_thread_id(config),
                node=node,
                decision_type=decision_type,
                issue_code=(
                    getattr(decision, "selected_issue_code", None)
                    if decision is not None
                    else None
                ),
                action=action.action.value if action is not None else None,
                state_version=catalog_state.state_version,
                transition_count=state["transition_count"],
                outcome=outcome,
                project_id=project_id,
            )
        )

    def decide(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        try:
            decision = services.decision_policy.decide(state["catalog_state"])
        except Exception:
            return _error_update(
                "INVALID_DECISION",
                "The workflow could not select a safe next decision.",
                "decide",
            )
        updated: CatalogWorkflowState = {**state, "last_decision": decision}
        emit("decision_selected", updated, config, node="decide")
        if decision.decision_type is DecisionType.WAIT_FOR_CLARIFICATION:
            emit("clarification_requested", updated, config, node="decide")
        return {"last_decision": decision, "workflow_error": None}

    def transition_guard(state: CatalogWorkflowState) -> dict[str, object]:
        decision = state.get("last_decision")
        route = _ROUTES.get(decision.decision_type) if decision is not None else None
        if route is None:
            return _error_update(
                "INVALID_DECISION",
                "The selected workflow decision has no safe route.",
                "transition_guard",
            )
        if (
            route in _OPERATIONAL_ROUTES
            and state["transition_count"] >= safety.max_transitions
        ):
            return _error_update(
                "TRANSITION_LIMIT_REACHED",
                "The workflow reached its configured transition limit.",
                "transition_guard",
            )
        return {"workflow_error": None}

    async def extract(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        emit("node_started", state, config, node="extract")
        try:
            result = await services.extractor.extract(state["catalog_state"].request)
            updated = services.state_updater.apply_extraction(
                state["catalog_state"], result
            )
        except Exception:
            return _operational_failure(
                state,
                "EXTRACTION_NODE_FAILED",
                "Requirement extraction could not be completed.",
                "extract",
            )
        return _completed_update(state, updated, config, emit, "extract")

    async def normalize(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        emit("node_started", state, config, node="normalize")
        extraction = state["catalog_state"].extraction_result
        if extraction is None:
            return _state_failure(state, "normalize")
        try:
            result = await services.normalizer.normalize(extraction)
            updated = services.state_updater.apply_normalization(
                state["catalog_state"], result
            )
        except Exception:
            return _operational_failure(
                state,
                "NORMALIZATION_NODE_FAILED",
                "Taxonomy normalization could not be completed.",
                "normalize",
            )
        return _completed_update(state, updated, config, emit, "normalize")

    def build_profile(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        emit("node_started", state, config, node="build_profile")
        catalog_state = state["catalog_state"]
        extraction = catalog_state.extraction_result
        normalization = catalog_state.normalization_result
        if extraction is None or normalization is None:
            return _state_failure(state, "build_profile")
        try:
            profile = services.profile_builder.build(
                request=catalog_state.request,
                extraction=extraction,
                normalization=normalization,
            )
            updated = services.state_updater.apply_profile(catalog_state, profile)
        except Exception:
            return _operational_failure(
                state,
                "PROFILE_BUILD_NODE_FAILED",
                "The candidate project profile could not be built.",
                "build_profile",
            )
        return _completed_update(state, updated, config, emit, "build_profile")

    def validate(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        emit("node_started", state, config, node="validate")
        profile = state["catalog_state"].candidate_profile
        if profile is None:
            return _state_failure(state, "validate")
        try:
            result = services.validator.validate(profile)
            updated = services.state_updater.apply_validation(
                state["catalog_state"], result
            )
        except Exception:
            return _operational_failure(
                state,
                "VALIDATION_NODE_FAILED",
                "Project profile validation could not be completed.",
                "validate",
            )
        return _completed_update(state, updated, config, emit, "validate")

    async def execute_recovery(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        emit("node_started", state, config, node="execute_recovery")
        catalog_state = state["catalog_state"]
        decision = state.get("last_decision")
        action = decision.action_request if decision is not None else None
        context = _recovery_context(catalog_state)
        if (
            decision is None
            or decision.decision_type is not DecisionType.EXECUTE_RECOVERY
            or action is None
            or context is None
        ):
            return _state_failure(state, "execute_recovery")
        try:
            result = await services.recovery_executor.execute(
                action_request=action,
                context=context,
            )
            updated = services.state_updater.apply_recovery_result(
                catalog_state, action, result
            )
        except Exception:
            return _operational_failure(
                state,
                "RECOVERY_NODE_FAILED",
                "The selected recovery action could not be completed.",
                "execute_recovery",
            )
        next_state: CatalogWorkflowState = {**state, "catalog_state": updated}
        emit("recovery_executed", next_state, config, node="execute_recovery")
        return _completed_update(state, updated, config, emit, "execute_recovery")

    def await_clarification(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        catalog_state = state["catalog_state"]
        pending = catalog_state.pending_clarification
        if pending is None:
            return _state_failure(state, "await_clarification")
        raw_response = interrupt(
            {
                "type": "clarification_required",
                "request_id": pending.request_id,
                "clarification_id": pending.clarification_id,
                "issue_code": pending.issue_code,
                "field": pending.field,
                "question": pending.question,
                "options": [item.model_dump(mode="json") for item in pending.options],
                "allow_free_text": pending.allow_free_text,
            }
        )
        try:
            response = ClarificationResponse.model_validate(raw_response)
        except ValidationError:
            return {
                **_operational_failure(
                    state,
                    "CLARIFICATION_NODE_FAILED",
                    "The clarification response was invalid.",
                    "await_clarification",
                    retryable=True,
                )
            }
        application = services.clarification_processor.apply(
            state=catalog_state,
            response=response,
        )
        next_count = state["transition_count"] + 1
        if application.status is ClarificationApplicationStatus.REJECTED:
            return {
                "transition_count": next_count,
                "workflow_error": WorkflowError(
                    code=application.error_code or "CLARIFICATION_NODE_FAILED",
                    message=application.message,
                    node="await_clarification",
                    retryable=True,
                ),
            }
        if application.updated_state is None:
            return _operational_failure(
                state,
                "CLARIFICATION_NODE_FAILED",
                "Clarification did not produce an updated state.",
                "await_clarification",
            )
        updated_state: CatalogWorkflowState = {
            **state,
            "catalog_state": application.updated_state,
            "transition_count": next_count,
            "workflow_error": None,
        }
        emit(
            "clarification_applied",
            updated_state,
            config,
            node="await_clarification",
        )
        return {
            "catalog_state": application.updated_state,
            "transition_count": next_count,
            "workflow_error": None,
        }

    def publish(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        emit("node_started", state, config, node="publish")
        decision = state.get("last_decision")
        if (
            decision is None
            or decision.decision_type is not DecisionType.PUBLISH_PROFILE
        ):
            return _state_failure(state, "publish")
        try:
            result = services.publication_service.publish(state["catalog_state"])
        except Exception:
            return _operational_failure(
                state,
                "PUBLICATION_NODE_FAILED",
                "Project publication could not be completed.",
                "publish",
            )
        next_count = state["transition_count"] + 1
        if (
            result.status
            in {
                PublicationStatus.PUBLISHED,
                PublicationStatus.ALREADY_PUBLISHED,
            }
            and result.updated_state is not None
        ):
            updated: CatalogWorkflowState = {
                **state,
                "catalog_state": result.updated_state,
                "last_publication_result": result,
                "transition_count": next_count,
                "workflow_error": None,
            }
            emit(
                "publication_succeeded"
                if result.status is PublicationStatus.PUBLISHED
                else "publication_idempotent",
                updated,
                config,
                node="publish",
                project_id=result.updated_state.published_project_id,
            )
            return {
                "catalog_state": result.updated_state,
                "last_publication_result": result,
                "transition_count": next_count,
                "workflow_error": None,
            }
        return {
            "last_publication_result": result,
            "transition_count": next_count,
            "workflow_error": WorkflowError(
                code=result.error_code or "PUBLICATION_NODE_FAILED",
                message=result.message,
                node="publish",
                retryable=result.status is PublicationStatus.FAILED,
            ),
        }

    def permanent_failure(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        error = state.get("workflow_error") or WorkflowError(
            code="INVALID_DECISION",
            message="The workflow terminated without a safe next action.",
            node="permanent_failure",
            retryable=False,
        )
        catalog_state = state["catalog_state"]
        if catalog_state.status is not CatalogStatus.PERMANENT_FAILURE:
            with suppress(Exception):
                catalog_state = services.state_updater.add_error(
                    catalog_state,
                    AgentError(
                        code=error.code,
                        message=error.message,
                        stage=catalog_state.stage,
                        retryable=False,
                    ),
                )
        updated: CatalogWorkflowState = {
            **state,
            "catalog_state": catalog_state,
            "workflow_error": error,
        }
        emit(
            "workflow_failed",
            updated,
            config,
            node="permanent_failure",
            outcome="permanent_failure",
        )
        return {"catalog_state": catalog_state, "workflow_error": error}

    def terminal_success(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        catalog_state = state["catalog_state"]
        if (
            catalog_state.status is not CatalogStatus.COMPLETED
            or catalog_state.stage is not CatalogStage.COMPLETED
            or catalog_state.published_project_id is None
            or catalog_state.validation_result is None
            or not catalog_state.validation_result.valid
        ):
            return _error_update(
                "STATE_UPDATE_FAILED",
                "The workflow reached success without a published valid state.",
                "terminal_success",
            )
        emit(
            "workflow_completed",
            state,
            config,
            node="terminal_success",
            outcome="completed",
            project_id=catalog_state.published_project_id,
        )
        return {}

    def terminal_escalated(
        state: CatalogWorkflowState, config: RunnableConfig
    ) -> dict[str, object]:
        catalog_state = state["catalog_state"]
        if (
            catalog_state.status is not CatalogStatus.ESCALATED
            or catalog_state.escalation is None
        ):
            return _error_update(
                "STATE_UPDATE_FAILED",
                "The workflow reached escalation without escalation state.",
                "terminal_escalated",
            )
        emit(
            "workflow_escalated",
            state,
            config,
            node="terminal_escalated",
            outcome="escalated",
        )
        return {}

    builder = StateGraph(CatalogWorkflowState)
    builder.add_node("decide", decide)
    builder.add_node("transition_guard", transition_guard)
    builder.add_node("extract", extract)
    builder.add_node("normalize", normalize)
    builder.add_node("build_profile", build_profile)
    builder.add_node("validate", validate)
    builder.add_node("execute_recovery", execute_recovery)
    builder.add_node("await_clarification", await_clarification)
    builder.add_node("publish", publish)
    builder.add_node("permanent_failure", permanent_failure)
    builder.add_node("terminal_success", terminal_success)
    builder.add_node("terminal_escalated", terminal_escalated)
    builder.add_edge(START, "decide")
    builder.add_edge("decide", "transition_guard")
    builder.add_conditional_edges(
        "transition_guard",
        _route_after_guard,
        {
            **{name: name for name in set(_ROUTES.values())},
            "permanent_failure": "permanent_failure",
        },
    )
    for node in (
        "extract",
        "normalize",
        "build_profile",
        "validate",
        "execute_recovery",
    ):
        builder.add_conditional_edges(
            node,
            _route_after_operation,
            {"decide": "decide", "permanent_failure": "permanent_failure"},
        )
    builder.add_conditional_edges(
        "await_clarification",
        _route_after_clarification,
        {
            "decide": "decide",
            "await_clarification": "await_clarification",
            "permanent_failure": "permanent_failure",
        },
    )
    builder.add_conditional_edges(
        "publish",
        _route_after_operation,
        {"decide": "decide", "permanent_failure": "permanent_failure"},
    )
    builder.add_conditional_edges(
        "terminal_success",
        _route_after_terminal,
        {"end": END, "permanent_failure": "permanent_failure"},
    )
    builder.add_conditional_edges(
        "terminal_escalated",
        _route_after_terminal,
        {"end": END, "permanent_failure": "permanent_failure"},
    )
    builder.add_edge("permanent_failure", END)
    return builder.compile(checkpointer=checkpointer)


def _thread_id(config: RunnableConfig) -> str:
    configurable = config.get("configurable", {})
    value = configurable.get("thread_id")
    return str(value)


def _route_after_guard(state: CatalogWorkflowState) -> str:
    if state.get("workflow_error") is not None:
        return "permanent_failure"
    decision = state.get("last_decision")
    return (
        _ROUTES.get(decision.decision_type, "permanent_failure")
        if decision
        else ("permanent_failure")
    )


def _route_after_operation(state: CatalogWorkflowState) -> str:
    return "permanent_failure" if state.get("workflow_error") else "decide"


def _route_after_clarification(state: CatalogWorkflowState) -> str:
    error = state.get("workflow_error")
    if error is not None:
        return "await_clarification" if error.retryable else "permanent_failure"
    return "decide"


def _route_after_terminal(state: CatalogWorkflowState) -> str:
    return "permanent_failure" if state.get("workflow_error") else "end"


def _recovery_context(catalog_state: object) -> RecoveryContext | None:
    from project_catalog_agent.catalog.contracts import CatalogAgentState

    state = cast(CatalogAgentState, catalog_state)
    if (
        state.extraction_result is None
        or state.normalization_result is None
        or state.candidate_profile is None
        or state.validation_result is None
    ):
        return None
    return RecoveryContext(
        request=state.request,
        extraction_result=state.extraction_result,
        normalization_result=state.normalization_result,
        candidate_profile=state.candidate_profile,
        validation_result=state.validation_result,
    )


def _error_update(code: str, message: str, node: str) -> dict[str, object]:
    return {
        "workflow_error": WorkflowError(
            code=code,
            message=message,
            node=node,
            retryable=False,
        )
    }


def _state_failure(
    state: CatalogWorkflowState,
    node: str,
) -> dict[str, object]:
    return _operational_failure(
        state,
        "STATE_UPDATE_FAILED",
        "The workflow state does not satisfy this node's preconditions.",
        node,
    )


def _operational_failure(
    state: CatalogWorkflowState,
    code: str,
    message: str,
    node: str,
    *,
    retryable: bool = False,
) -> dict[str, object]:
    return {
        "transition_count": state["transition_count"] + 1,
        "workflow_error": WorkflowError(
            code=code,
            message=message,
            node=node,
            retryable=retryable,
        ),
    }


def _completed_update(
    state: CatalogWorkflowState,
    catalog_state: object,
    config: RunnableConfig,
    emit: object,
    node: str,
) -> dict[str, object]:
    from collections.abc import Callable

    from project_catalog_agent.catalog.contracts import CatalogAgentState

    updated = cast(CatalogAgentState, catalog_state)
    next_state: CatalogWorkflowState = {
        **state,
        "catalog_state": updated,
        "transition_count": state["transition_count"] + 1,
        "workflow_error": None,
    }
    emitter = cast(
        Callable[..., None],
        emit,
    )
    emitter("node_completed", next_state, config, node=node)
    return {
        "catalog_state": updated,
        "transition_count": next_state["transition_count"],
        "workflow_error": None,
    }
