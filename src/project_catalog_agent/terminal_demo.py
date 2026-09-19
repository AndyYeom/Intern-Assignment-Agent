"""Interactive controlled workflow demonstration for the Project Catalog Agent."""

import argparse
import asyncio
import getpass
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from dotenv import load_dotenv

from project_catalog_agent.actions import RecoveryActionExecutor
from project_catalog_agent.admin import (
    AdminAuthenticator,
    AdminCredentialConfig,
    InMemoryAuditSink,
)
from project_catalog_agent.admin.terminal import (
    TerminalAdminLogin,
    TerminalClarificationHandler,
    TerminalEscalationHandler,
)
from project_catalog_agent.agent import (
    CatalogDecisionPolicy,
    CatalogStateUpdater,
    ClarificationResponseProcessor,
    EscalationReviewProcessor,
)
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CreateProjectRequest,
)
from project_catalog_agent.demo.controller import TerminalDemoController
from project_catalog_agent.demo.input import (
    InputReader,
    OutputWriter,
    prompt_bounded_text,
    prompt_menu_choice,
    prompt_yes_no,
)
from project_catalog_agent.demo.scenarios import (
    DemoScenario,
    DemoScenarioBundle,
    scenario_bundle,
)
from project_catalog_agent.demo.services import (
    ControlledRequirementExtractor,
    ControlledTaxonomyNormalizer,
)
from project_catalog_agent.errors import AdminCredentialConfigurationError
from project_catalog_agent.persistence import (
    ComponentVersions,
    InMemoryProjectRepository,
    ProjectPublicationGuard,
    ProjectPublicationService,
    ProjectRepository,
)
from project_catalog_agent.profile import ProjectProfileBuilder, ProjectProfileValidator
from project_catalog_agent.taxonomy import JsonTaxonomyRepository

PasswordReader = Callable[[str], str]
Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]

_MENU = {
    "1": DemoScenario.AMBIGUOUS_CLOUD,
    "2": DemoScenario.MISSING_LEVEL,
    "3": DemoScenario.UNMAPPED_SKILL,
    "4": DemoScenario.EXHAUSTED_RECOVERY,
    "5": DemoScenario.CUSTOM,
}


class TerminalDemoApplication:
    """Render the main menu and construct isolated controlled workflow runs."""

    def __init__(
        self,
        *,
        input_reader: InputReader = input,
        password_reader: PasswordReader = getpass.getpass,
        output_writer: OutputWriter = print,
        clock: Clock = lambda: datetime.now(UTC),
        id_generator: IdGenerator = lambda: uuid4().hex[:12].upper(),
        max_transitions: int = 20,
        show_state: bool = False,
        verbose: bool = False,
        project_repository: ProjectRepository | None = None,
    ) -> None:
        self._input_reader = input_reader
        self._password_reader = password_reader
        self._output_writer = output_writer
        self._clock = clock
        self._id_generator = id_generator
        self._max_transitions = max_transitions
        self._show_state = show_state
        self._verbose = verbose
        self.last_state: CatalogAgentState | None = None
        self._project_repository = (
            project_repository
            if project_repository is not None
            else InMemoryProjectRepository()
        )

    async def run(self, scenario: DemoScenario | None = None) -> int:
        """Run one selected scenario or continue showing the interactive menu."""
        if scenario is not None:
            bundle = self._select_bundle(scenario)
            if bundle is not None:
                await self._run_bundle(bundle)
            return 0
        while True:
            self._render_menu()
            choice = prompt_menu_choice(
                "Select an option: ",
                {str(index): str(index) for index in range(1, 8)},
                input_reader=self._input_reader,
                output_writer=self._output_writer,
            )
            if choice is None or choice == "7":
                self._output_writer("Demo closed.")
                return 0
            if choice == "6":
                self._show_accounts()
                continue
            selected = _MENU[choice]
            bundle = self._select_bundle(selected)
            if bundle is not None:
                await self._run_bundle(bundle)

    def _select_bundle(self, scenario: DemoScenario) -> DemoScenarioBundle | None:
        if scenario is not DemoScenario.CUSTOM:
            return scenario_bundle(scenario)
        name = prompt_bounded_text(
            "Project name: ",
            max_length=200,
            input_reader=self._input_reader,
            output_writer=self._output_writer,
        )
        if name is None:
            return None
        description = prompt_bounded_text(
            "Project description: ",
            max_length=20_000,
            input_reader=self._input_reader,
            output_writer=self._output_writer,
        )
        if description is None:
            return None
        live = prompt_yes_no(
            "Use live extraction service? [y/N]: ",
            input_reader=self._input_reader,
            output_writer=self._output_writer,
        )
        if live:
            self._output_writer(
                "Live extraction is not configured for this demo; using controlled "
                "deterministic extraction."
            )
        self._output_writer("1. Normal valid project")
        self._output_writer("2. Ambiguous requirement")
        self._output_writer("3. Missing required level")
        self._output_writer("4. Unknown skill")
        kind = prompt_menu_choice(
            "Select deterministic behavior: ",
            {str(index): str(index) for index in range(1, 5)},
            input_reader=self._input_reader,
            output_writer=self._output_writer,
        )
        if kind is None:
            return None
        request = CreateProjectRequest(
            request_id=f"DEMO-{self._id_generator()}",
            project_name=name,
            project_description=description,
        )
        return scenario_bundle(
            DemoScenario.CUSTOM,
            request=request,
            custom_kind=kind,
        )

    async def _run_bundle(self, bundle: DemoScenarioBundle) -> None:
        self._output_writer("Mode: controlled demonstration")
        self._output_writer(f"Scenario: {bundle.scenario.value}")
        if self._verbose:
            self._output_writer("Verbose transition display: enabled")
        repository = JsonTaxonomyRepository()
        extractor = ControlledRequirementExtractor(bundle.extraction)
        normalizer = ControlledTaxonomyNormalizer(bundle.normalization)
        builder = ProjectProfileBuilder()
        updater = CatalogStateUpdater()
        audit = InMemoryAuditSink()
        authenticator = self._load_authenticator()
        clarification_handler: TerminalClarificationHandler | None = None
        escalation_handler: TerminalEscalationHandler | None = None
        if authenticator is not None:
            login = TerminalAdminLogin(
                authenticator=authenticator,
                max_attempts=3,
                input_reader=self._input_reader,
                password_reader=self._password_reader,
                output_writer=self._output_writer,
            )
            clarification_handler = TerminalClarificationHandler(
                login=login,
                processor=ClarificationResponseProcessor(
                    taxonomy_repository=repository,
                    state_updater=updater,
                    admin_authorizer=authenticator,
                ),
                audit_sink=audit,
                input_reader=self._input_reader,
                output_writer=self._output_writer,
                clock=self._clock,
            )
            escalation_handler = TerminalEscalationHandler(
                login=login,
                processor=EscalationReviewProcessor(
                    state_updater=updater,
                    admin_authorizer=authenticator,
                ),
                audit_sink=audit,
                input_reader=self._input_reader,
                output_writer=self._output_writer,
                clock=self._clock,
            )
        recovery = RecoveryActionExecutor(
            extractor=extractor,
            normalizer=normalizer,
            profile_builder=builder,
            taxonomy_repository=repository,
        )
        controller = TerminalDemoController(
            extractor=extractor,
            normalizer=normalizer,
            profile_builder=builder,
            validator=ProjectProfileValidator(taxonomy_repository=repository),
            recovery_executor=recovery,
            decision_policy=CatalogDecisionPolicy(bundle.policy_config),
            state_updater=updater,
            publication_service=ProjectPublicationService(
                repository=self._project_repository,
                guard=ProjectPublicationGuard(lambda: repository.version),
                state_updater=updater,
                project_id_factory=lambda: f"PRJ-{self._id_generator()}",
                clock=self._clock,
                taxonomy_version_provider=lambda: repository.version,
                component_versions=ComponentVersions(
                    extractor_version="controlled-demo-v1",
                    normalizer_version="controlled-demo-v1",
                    profile_builder_version="v1",
                    validator_version="v1",
                ),
            ),
            clarification_handler=clarification_handler,
            escalation_handler=escalation_handler,
            audit_sink=audit,
            input_reader=self._input_reader,
            output_writer=self._output_writer,
            max_transitions=self._max_transitions,
            show_state=self._show_state,
        )
        self.last_state = await controller.run(bundle.request)

    @staticmethod
    def _load_authenticator() -> AdminAuthenticator | None:
        try:
            config = AdminCredentialConfig.from_environment()
        except AdminCredentialConfigurationError:
            return None
        return AdminAuthenticator(credentials=config.credentials)

    def _show_accounts(self) -> None:
        load_dotenv()
        clarifier_name = os.getenv("CLARIFIER_USERNAME", "clarifier").strip()
        escalator_name = os.getenv("ESCALATOR_USERNAME", "escalator").strip()
        clarifier_set = bool(os.getenv("CLARIFIER_PASSWORD_HASH", "").strip())
        escalator_set = bool(os.getenv("ESCALATOR_PASSWORD_HASH", "").strip())
        self._output_writer(
            f"{clarifier_name} → role: clarifier → configured: "
            f"{'yes' if clarifier_set else 'no'}"
        )
        self._output_writer(
            f"{escalator_name} → role: escalator → configured: "
            f"{'yes' if escalator_set else 'no'}"
        )

    def _render_menu(self) -> None:
        self._output_writer("=" * 60)
        self._output_writer("Project Catalog Agent — Interactive Terminal Demo")
        self._output_writer("=" * 60)
        self._output_writer("1. Run clarification scenario: ambiguous cloud platform")
        self._output_writer("2. Run clarification scenario: missing required level")
        self._output_writer("3. Run escalation scenario: unmapped skill")
        self._output_writer("4. Run escalation scenario: exhausted recovery")
        self._output_writer("5. Enter a custom project")
        self._output_writer("6. View configured demo accounts")
        self._output_writer("7. Exit")


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse safe demo options; credential values are intentionally unsupported."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[item.value for item in DemoScenario])
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--show-state", action="store_true")
    parser.add_argument("--max-transitions", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the interactive terminal demonstration."""
    args = parse_arguments(argv)
    if args.max_transitions < 1:
        raise SystemExit("--max-transitions must be at least one")
    scenario = DemoScenario(args.scenario) if args.scenario else None
    application = TerminalDemoApplication(
        max_transitions=args.max_transitions,
        show_state=args.show_state,
        verbose=args.verbose,
    )
    return asyncio.run(application.run(scenario))


if __name__ == "__main__":
    raise SystemExit(main())
