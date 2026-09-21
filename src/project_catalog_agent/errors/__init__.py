"""Application-specific exception types."""

from project_catalog_agent.errors.authentication import (
    AdminCredentialConfigurationError,
    AuthenticationInfrastructureError,
)
from project_catalog_agent.errors.decision import InvalidDecisionStateError
from project_catalog_agent.errors.extraction import (
    RequirementExtractionConfigurationError,
    RequirementExtractionError,
    RequirementExtractionResponseError,
)
from project_catalog_agent.errors.profile import ProjectProfileBuildError
from project_catalog_agent.errors.state import InvalidStateTransitionError

__all__ = [
    "AdminCredentialConfigurationError",
    "AuthenticationInfrastructureError",
    "InvalidDecisionStateError",
    "InvalidStateTransitionError",
    "ProjectProfileBuildError",
    "RequirementExtractionConfigurationError",
    "RequirementExtractionError",
    "RequirementExtractionResponseError",
]
