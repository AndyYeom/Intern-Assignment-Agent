"""Immutable dependency container for workflow node closures."""

from dataclasses import dataclass

from project_catalog_agent.actions import RecoveryActionExecutor
from project_catalog_agent.agent import (
    CatalogDecisionPolicy,
    CatalogStateUpdater,
    ClarificationResponseProcessor,
)
from project_catalog_agent.extraction import RequirementExtractor
from project_catalog_agent.persistence import ProjectPublicationService
from project_catalog_agent.profile import ProjectProfileBuilder, ProjectProfileValidator
from project_catalog_agent.taxonomy import TaxonomyNormalizer


@dataclass(frozen=True, slots=True)
class CatalogWorkflowServices:
    """Runtime services deliberately excluded from checkpoint state."""

    extractor: RequirementExtractor
    normalizer: TaxonomyNormalizer
    profile_builder: ProjectProfileBuilder
    validator: ProjectProfileValidator
    recovery_executor: RecoveryActionExecutor
    decision_policy: CatalogDecisionPolicy
    state_updater: CatalogStateUpdater
    clarification_processor: ClarificationResponseProcessor
    publication_service: ProjectPublicationService
