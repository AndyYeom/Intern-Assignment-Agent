"""Controlled complete-workflow fixtures."""

from collections.abc import Callable
from datetime import UTC, datetime

from project_catalog_agent.actions import RecoveryActionExecutor
from project_catalog_agent.admin import AdminRole
from project_catalog_agent.agent import (
    CatalogDecisionPolicy,
    CatalogStateUpdater,
    ClarificationResponseProcessor,
)
from project_catalog_agent.demo.scenarios import DemoScenarioBundle
from project_catalog_agent.demo.services import (
    ControlledRequirementExtractor,
    ControlledTaxonomyNormalizer,
)
from project_catalog_agent.persistence import (
    ComponentVersions,
    InMemoryProjectRepository,
    ProjectPublicationGuard,
    ProjectPublicationService,
    ProjectRepository,
)
from project_catalog_agent.profile import ProjectProfileBuilder, ProjectProfileValidator
from project_catalog_agent.taxonomy import JsonTaxonomyRepository
from project_catalog_agent.workflow import (
    CatalogWorkflow,
    CatalogWorkflowConfig,
    CatalogWorkflowServices,
    InMemoryWorkflowEventSink,
    build_catalog_workflow_graph,
    create_memory_checkpointer,
)

NOW = datetime(2026, 4, 1, 12, tzinfo=UTC)


class ControlledAuthorizer:
    """Authorize the controlled identities for their exact roles."""

    def is_authorized(self, *, actor_id: str, required_role: AdminRole) -> bool:
        return (actor_id, required_role) in {
            ("clarifier", AdminRole.CLARIFIER),
            ("escalator", AdminRole.ESCALATOR),
        }


def workflow_for_bundle(
    bundle: DemoScenarioBundle,
    *,
    repository: ProjectRepository | None = None,
    max_transitions: int = 30,
    project_id_factory: Callable[[], str] = lambda: "PRJ-WORKFLOW-001",
) -> tuple[CatalogWorkflow, ProjectRepository, InMemoryWorkflowEventSink]:
    """Build a workflow with real domain services and controlled I/O services."""
    taxonomy = JsonTaxonomyRepository()
    updater = CatalogStateUpdater()
    builder = ProjectProfileBuilder()
    extractor = ControlledRequirementExtractor(bundle.extraction)
    normalizer = ControlledTaxonomyNormalizer(bundle.normalization)
    project_repository = repository or InMemoryProjectRepository()
    events = InMemoryWorkflowEventSink()
    services = CatalogWorkflowServices(
        extractor=extractor,
        normalizer=normalizer,
        profile_builder=builder,
        validator=ProjectProfileValidator(taxonomy_repository=taxonomy),
        recovery_executor=RecoveryActionExecutor(
            extractor=extractor,
            normalizer=normalizer,
            profile_builder=builder,
            taxonomy_repository=taxonomy,
        ),
        decision_policy=CatalogDecisionPolicy(bundle.policy_config),
        state_updater=updater,
        clarification_processor=ClarificationResponseProcessor(
            taxonomy_repository=taxonomy,
            state_updater=updater,
            admin_authorizer=ControlledAuthorizer(),
        ),
        publication_service=ProjectPublicationService(
            repository=project_repository,
            guard=ProjectPublicationGuard(lambda: taxonomy.version),
            state_updater=updater,
            project_id_factory=project_id_factory,
            clock=lambda: NOW,
            taxonomy_version_provider=lambda: taxonomy.version,
            component_versions=ComponentVersions(
                extractor_version="controlled-v1",
                normalizer_version="controlled-v1",
                profile_builder_version="v1",
                validator_version="v1",
            ),
        ),
    )
    graph = build_catalog_workflow_graph(
        services=services,
        checkpointer=create_memory_checkpointer(),
        workflow_config=CatalogWorkflowConfig(max_transitions=max_transitions),
        event_sink=events,
    )
    return CatalogWorkflow(graph=graph, event_sink=events), project_repository, events
