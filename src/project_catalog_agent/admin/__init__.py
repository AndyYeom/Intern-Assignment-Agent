"""Secure administrator authentication and audit primitives."""

from project_catalog_agent.admin.audit import AuditSink, InMemoryAuditSink
from project_catalog_agent.admin.authentication import AdminAuthenticator
from project_catalog_agent.admin.authorization import AdminAuthorizer
from project_catalog_agent.admin.config import (
    AdminCredential,
    AdminCredentialConfig,
)
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

__all__ = [
    "AdminAuditEvent",
    "AdminAuthenticator",
    "AdminAuthorizer",
    "AdminCredential",
    "AdminCredentialConfig",
    "AdminRole",
    "AuditSink",
    "AuthenticationResult",
    "AuthenticationStatus",
    "EscalationDecision",
    "EscalationReviewResponse",
    "EscalationReviewResult",
    "EscalationReviewStatus",
    "InMemoryAuditSink",
]
