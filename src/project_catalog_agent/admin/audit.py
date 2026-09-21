"""Credential-free administrator audit sinks."""

from typing import Protocol

from project_catalog_agent.admin.contracts import AdminAuditEvent


class AuditSink(Protocol):
    """Boundary for recording safe administrator audit events."""

    def record(self, event: AdminAuditEvent) -> None:
        """Record one credential-free event."""
        ...


class InMemoryAuditSink:
    """Simple detached event collector for tests and V1 terminal use."""

    def __init__(self) -> None:
        self._events: list[AdminAuditEvent] = []

    @property
    def events(self) -> tuple[AdminAuditEvent, ...]:
        """Return detached events in recording order."""
        return tuple(item.model_copy(deep=True) for item in self._events)

    def record(self, event: AdminAuditEvent) -> None:
        """Store a detached copy without credentials or raw terminal input."""
        self._events.append(event.model_copy(deep=True))
