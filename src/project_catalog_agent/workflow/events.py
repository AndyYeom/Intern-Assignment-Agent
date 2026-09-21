"""Credential-free workflow observability events."""

from collections.abc import Callable
from typing import Annotated, Protocol

from pydantic import Field

from project_catalog_agent.catalog.contracts import ContractModel

NonEmptyString = Annotated[str, Field(min_length=1)]


class WorkflowEvent(ContractModel):
    """One structured event containing only allow-listed operational fields."""

    event: NonEmptyString
    request_id: NonEmptyString
    thread_id: NonEmptyString
    node: str | None = None
    decision_type: str | None = None
    issue_code: str | None = None
    action: str | None = None
    state_version: int
    transition_count: int
    outcome: str | None = None
    project_id: str | None = None


class WorkflowEventSink(Protocol):
    """Receive safe structured workflow events."""

    def __call__(self, event: WorkflowEvent) -> None:
        """Record one event."""
        ...


class InMemoryWorkflowEventSink:
    """Retain detached safe events for tests and local demonstrations."""

    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    def __call__(self, event: WorkflowEvent) -> None:
        self.events.append(event.model_copy(deep=True))


def discard_workflow_event(event: WorkflowEvent) -> None:
    """Default event sink for callers that do not configure logging."""
    del event


EventSink = Callable[[WorkflowEvent], None]
