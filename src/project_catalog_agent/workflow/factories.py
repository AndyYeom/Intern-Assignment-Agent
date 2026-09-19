"""Dependency factories for local, controlled, and test workflow runtimes."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver

from project_catalog_agent.actions import RecoveryActionExecutor
from project_catalog_agent.admin import (
    AdminAuthenticator,
    AdminAuthorizer,
    AdminCredentialConfig,
)
from project_catalog_agent.agent import (
    CatalogDecisionPolicy,
    CatalogStateUpdater,
    ClarificationResponseProcessor,
    EscalationReviewProcessor,
)
from project_catalog_agent.config.settings import Settings
from project_catalog_agent.demo.scenarios import DemoScenarioBundle
from project_catalog_agent.demo.services import (
    ControlledRequirementExtractor,
    ControlledTaxonomyNormalizer,
)
from project_catalog_agent.extraction import LLMRequirementExtractor
from project_catalog_agent.llm import OpenAIStructuredLLMClient
from project_catalog_agent.persistence import (
    ComponentVersions,
    ProjectPublicationGuard,
    ProjectPublicationService,
    ProjectRepository,
    SQLiteProjectRepository,
)
from project_catalog_agent.profile import ProjectProfileBuilder, ProjectProfileValidator
from project_catalog_agent.taxonomy import (
    HybridTaxonomyNormalizer,
    JsonTaxonomyRepository,
    LLMTaxonomyMappingSelector,
)
from project_catalog_agent.workflow.checkpoint import open_async_sqlite_checkpointer
from project_catalog_agent.workflow.contracts import CatalogWorkflowConfig
from project_catalog_agent.workflow.events import EventSink, discard_workflow_event
from project_catalog_agent.workflow.facade import CatalogWorkflow
from project_catalog_agent.workflow.graph import build_catalog_workflow_graph
from project_catalog_agent.workflow.services import CatalogWorkflowServices


@dataclass(frozen=True, slots=True)
class LocalWorkflowRuntime:
    """Local application services retained outside checkpoint state."""

    workflow: CatalogWorkflow
    project_repository: ProjectRepository
    authenticator: AdminAuthenticator
    escalation_processor: EscalationReviewProcessor


def create_workflow(
    *,
    services: CatalogWorkflowServices,
    checkpointer: BaseCheckpointSaver[str],
    config: CatalogWorkflowConfig | None = None,
    event_sink: EventSink = discard_workflow_event,
) -> CatalogWorkflow:
    """Create a workflow from explicit dependencies for tests or controlled demos."""
    workflow_config = config or CatalogWorkflowConfig()
    graph = build_catalog_workflow_graph(
        services=services,
        checkpointer=checkpointer,
        workflow_config=workflow_config,
        event_sink=event_sink,
    )
    return CatalogWorkflow(
        graph=graph,
        event_sink=event_sink,
        recursion_limit=workflow_config.max_transitions * 4 + 10,
    )


def create_controlled_workflow(
    *,
    bundle: DemoScenarioBundle,
    repository: ProjectRepository,
    checkpointer: BaseCheckpointSaver[str],
    admin_authorizer: AdminAuthorizer,
    config: CatalogWorkflowConfig | None = None,
    event_sink: EventSink = discard_workflow_event,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    project_id_factory: Callable[[], str] = lambda: f"PRJ-{uuid4().hex.upper()}",
) -> CatalogWorkflow:
    """Create deterministic controlled I/O around the real domain workflow."""
    taxonomy = JsonTaxonomyRepository()
    updater = CatalogStateUpdater()
    builder = ProjectProfileBuilder()
    extractor = ControlledRequirementExtractor(bundle.extraction)
    normalizer = ControlledTaxonomyNormalizer(bundle.normalization)
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
            admin_authorizer=admin_authorizer,
        ),
        publication_service=ProjectPublicationService(
            repository=repository,
            guard=ProjectPublicationGuard(lambda: taxonomy.version),
            state_updater=updater,
            project_id_factory=project_id_factory,
            clock=clock,
            taxonomy_version_provider=lambda: taxonomy.version,
            component_versions=ComponentVersions(
                extractor_version="controlled-v1",
                normalizer_version="controlled-v1",
                profile_builder_version="v1",
                validator_version="v1",
            ),
        ),
    )
    return create_workflow(
        services=services,
        checkpointer=checkpointer,
        config=config,
        event_sink=event_sink,
    )


@asynccontextmanager
async def open_local_sqlite_workflow(
    *,
    project_database: Path,
    checkpoint_database: Path,
    settings: Settings | None = None,
    config: CatalogWorkflowConfig | None = None,
    event_sink: EventSink = discard_workflow_event,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    project_id_factory: Callable[[], str] = lambda: f"PRJ-{uuid4().hex.upper()}",
) -> AsyncIterator[LocalWorkflowRuntime]:
    """Open a durable local workflow without deleting either SQLite database."""
    application_settings = settings or Settings()
    taxonomy = JsonTaxonomyRepository()
    llm_client = OpenAIStructuredLLMClient.from_settings(application_settings)
    extractor = LLMRequirementExtractor(llm_client)
    normalizer = HybridTaxonomyNormalizer(
        taxonomy,
        LLMTaxonomyMappingSelector(llm_client),
    )
    builder = ProjectProfileBuilder()
    updater = CatalogStateUpdater()
    credentials = AdminCredentialConfig.from_environment()
    authenticator = AdminAuthenticator(credentials=credentials.credentials)
    repository = SQLiteProjectRepository(project_database)
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
        decision_policy=CatalogDecisionPolicy(),
        state_updater=updater,
        clarification_processor=ClarificationResponseProcessor(
            taxonomy_repository=taxonomy,
            state_updater=updater,
            admin_authorizer=authenticator,
        ),
        publication_service=ProjectPublicationService(
            repository=repository,
            guard=ProjectPublicationGuard(lambda: taxonomy.version),
            state_updater=updater,
            project_id_factory=project_id_factory,
            clock=clock,
            taxonomy_version_provider=lambda: taxonomy.version,
            component_versions=ComponentVersions(
                extractor_version="step-4",
                normalizer_version="step-5",
                profile_builder_version="step-6",
                validator_version="step-7",
            ),
        ),
    )
    async with open_async_sqlite_checkpointer(checkpoint_database) as checkpointer:
        yield LocalWorkflowRuntime(
            workflow=create_workflow(
                services=services,
                checkpointer=checkpointer,
                config=config,
                event_sink=event_sink,
            ),
            project_repository=repository,
            authenticator=authenticator,
            escalation_processor=EscalationReviewProcessor(
                state_updater=updater,
                admin_authorizer=authenticator,
            ),
        )
