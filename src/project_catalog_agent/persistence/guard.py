"""Pure deterministic guard for validated-project publication."""

from collections.abc import Callable

from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    IssueSeverity,
)
from project_catalog_agent.persistence.contracts import (
    PublicationErrorCode,
    PublicationGuardResult,
)


class ProjectPublicationGuard:
    """Reject incomplete or unresolved profiles without repairing artifacts."""

    def __init__(self, taxonomy_version_provider: Callable[[], str]) -> None:
        self._taxonomy_version_provider = taxonomy_version_provider

    def evaluate(self, state: CatalogAgentState) -> PublicationGuardResult:
        """Evaluate publication rules in a stable first-failure order."""
        profile = state.candidate_profile
        if profile is None:
            return _rejected(
                PublicationErrorCode.PROFILE_MISSING,
                "A candidate project profile is required.",
            )
        validation = state.validation_result
        if validation is None:
            return _rejected(
                PublicationErrorCode.VALIDATION_MISSING,
                "A validation result is required.",
            )
        if not validation.valid:
            return _rejected(
                PublicationErrorCode.PROFILE_INVALID,
                "The candidate project profile is invalid.",
            )
        if any(issue.severity is IssueSeverity.BLOCKING for issue in validation.issues):
            return _rejected(
                PublicationErrorCode.BLOCKING_ISSUES_PRESENT,
                "Blocking validation issues prevent publication.",
            )
        if state.pending_clarification is not None:
            return _rejected(
                PublicationErrorCode.PENDING_CLARIFICATION,
                "A pending clarification prevents publication.",
            )
        if state.escalation is not None:
            return _rejected(
                PublicationErrorCode.ACTIVE_ESCALATION,
                "An active escalation prevents publication.",
            )
        if state.status is CatalogStatus.AWAITING_CLARIFICATION:
            return _rejected(
                PublicationErrorCode.PENDING_CLARIFICATION,
                "An awaiting-clarification state cannot be published.",
            )
        if state.status is CatalogStatus.ESCALATED:
            return _rejected(
                PublicationErrorCode.ACTIVE_ESCALATION,
                "An escalated state cannot be published.",
            )
        if profile.request_id != state.request.request_id:
            return _rejected(
                PublicationErrorCode.REQUEST_ID_MISMATCH,
                "The profile request identity does not match the state.",
            )
        if profile.unresolved_requirements or profile.unresolved_skills:
            return _rejected(
                PublicationErrorCode.UNRESOLVED_REQUIREMENTS_PRESENT,
                "Unresolved requirements prevent publication.",
            )
        if any(
            not requirement.skill_id.strip() or not requirement.canonical_name.strip()
            for requirement in profile.requirements
        ):
            return _rejected(
                PublicationErrorCode.PROFILE_INVALID,
                "Resolved requirements must identify canonical taxonomy skills.",
            )
        if not self._taxonomy_version_provider().strip():
            return _rejected(
                PublicationErrorCode.TAXONOMY_VERSION_MISSING,
                "A taxonomy version is required for publication.",
            )
        if (
            state.stage is not CatalogStage.VALIDATED
            or state.status is not CatalogStatus.PROCESSING
        ):
            return _rejected(
                PublicationErrorCode.INVALID_PUBLICATION_STATE,
                "Only a validated processing state may be published.",
            )
        return PublicationGuardResult(
            publishable=True,
            message="The validated profile is ready for publication.",
        )


def _rejected(
    code: PublicationErrorCode,
    message: str,
) -> PublicationGuardResult:
    return PublicationGuardResult(
        publishable=False,
        error_code=code.value,
        message=message,
    )
