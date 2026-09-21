"""Bounded workflow controller used only by the interactive terminal demo."""

import json

from project_catalog_agent.actions import RecoveryActionExecutor
from project_catalog_agent.admin import InMemoryAuditSink
from project_catalog_agent.admin.terminal import (
    TerminalClarificationHandler,
    TerminalEscalationHandler,
)
from project_catalog_agent.agent import CatalogDecisionPolicy, CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogDecision,
    CatalogStatus,
    CreateProjectRequest,
    DecisionType,
    RecoveryContext,
    create_initial_catalog_state,
)
from project_catalog_agent.demo.input import InputReader, OutputWriter, prompt_yes_no
from project_catalog_agent.demo.redaction import redact_sensitive
from project_catalog_agent.extraction import RequirementExtractor
from project_catalog_agent.persistence import ProjectPublicationService
from project_catalog_agent.profile import ProjectProfileBuilder, ProjectProfileValidator
from project_catalog_agent.taxonomy import TaxonomyNormalizer


class TerminalDemoController:
    """Run the real bounded pipeline around controlled demo services."""

    def __init__(
        self,
        *,
        extractor: RequirementExtractor,
        normalizer: TaxonomyNormalizer,
        profile_builder: ProjectProfileBuilder,
        validator: ProjectProfileValidator,
        recovery_executor: RecoveryActionExecutor,
        decision_policy: CatalogDecisionPolicy,
        state_updater: CatalogStateUpdater,
        publication_service: ProjectPublicationService,
        clarification_handler: TerminalClarificationHandler | None,
        escalation_handler: TerminalEscalationHandler | None,
        audit_sink: InMemoryAuditSink,
        input_reader: InputReader = input,
        output_writer: OutputWriter = print,
        max_transitions: int = 20,
        show_state: bool = False,
    ) -> None:
        if max_transitions < 1:
            raise ValueError("max_transitions must be at least one")
        self._extractor = extractor
        self._normalizer = normalizer
        self._profile_builder = profile_builder
        self._validator = validator
        self._recovery_executor = recovery_executor
        self._decision_policy = decision_policy
        self._state_updater = state_updater
        self._publication_service = publication_service
        self._clarification_handler = clarification_handler
        self._escalation_handler = escalation_handler
        self._audit_sink = audit_sink
        self._input_reader = input_reader
        self._output_writer = output_writer
        self._max_transitions = max_transitions
        self._show_state = show_state

    async def run(self, request: CreateProjectRequest) -> CatalogAgentState:
        """Execute a bounded pipeline and pause safely at protected input gates."""
        state = create_initial_catalog_state(request)
        transition_count = 0
        stopped = False
        for transition_count in range(1, self._max_transitions + 1):
            decision = self._decision_policy.decide(state)
            self._display_transition(transition_count, state, decision)
            if decision.decision_type is DecisionType.RUN_EXTRACTION:
                state = self._state_updater.apply_extraction(
                    state, await self._extractor.extract(state.request)
                )
            elif decision.decision_type is DecisionType.RUN_NORMALIZATION:
                extraction = state.extraction_result
                if extraction is None:
                    break
                state = self._state_updater.apply_normalization(
                    state, await self._normalizer.normalize(extraction)
                )
            elif decision.decision_type is DecisionType.BUILD_PROFILE:
                extraction = state.extraction_result
                normalization = state.normalization_result
                if extraction is None or normalization is None:
                    break
                profile = self._profile_builder.build(
                    request=state.request,
                    extraction=extraction,
                    normalization=normalization,
                )
                state = self._state_updater.apply_profile(state, profile)
            elif decision.decision_type is DecisionType.RUN_VALIDATION:
                if state.candidate_profile is None:
                    break
                state = self._state_updater.apply_validation(
                    state, self._validator.validate(state.candidate_profile)
                )
            elif decision.decision_type is DecisionType.EXECUTE_RECOVERY:
                action_request = decision.action_request
                context = self._recovery_context(state)
                if action_request is None or context is None:
                    break
                recovery_result = await self._recovery_executor.execute(
                    action_request=action_request,
                    context=context,
                )
                state = self._state_updater.apply_recovery_result(
                    state, action_request, recovery_result
                )
            elif decision.decision_type is DecisionType.PUBLISH_PROFILE:
                publication = self._publication_service.publish(state)
                self._output_writer(f"Publication status: {publication.status.value}")
                if publication.stored_project is not None:
                    label = (
                        "Existing project ID"
                        if publication.status.value == "already_published"
                        else "Project ID"
                    )
                    self._output_writer(
                        f"{label}: {publication.stored_project.project_id}"
                    )
                if publication.updated_state is None:
                    self._output_writer(
                        f"Reason: {publication.error_code or 'REPOSITORY_FAILURE'}"
                    )
                    stopped = True
                    break
                state = publication.updated_state
            elif decision.decision_type is DecisionType.WAIT_FOR_CLARIFICATION:
                if not self._confirm("Answer clarification now? [y/N]: "):
                    stopped = True
                    break
                if self._clarification_handler is None:
                    self._credentials_missing()
                    stopped = True
                    break
                clarification_result = self._clarification_handler.handle(state=state)
                if clarification_result.updated_state is None:
                    self._output_writer("State was not modified.")
                    stopped = True
                    break
                state = clarification_result.updated_state
            elif decision.decision_type is DecisionType.STOP_ESCALATED:
                if state.escalation_review_history:
                    stopped = True
                    break
                if not self._confirm("Review escalation now? [y/N]: "):
                    stopped = True
                    break
                if self._escalation_handler is None:
                    self._credentials_missing()
                    stopped = True
                    break
                escalation_result = self._escalation_handler.handle(state=state)
                if escalation_result.updated_state is not None:
                    state = escalation_result.updated_state
                else:
                    self._output_writer("State was not modified.")
                stopped = True
                break
            elif decision.decision_type in {
                DecisionType.COMPLETE,
                DecisionType.STOP_PERMANENT_FAILURE,
            }:
                stopped = True
                break
            self._display_new_state(state)
        if not stopped and transition_count >= self._max_transitions:
            self._output_writer("Maximum transition limit reached; processing stopped.")
        self._display_summary(state, transition_count)
        return state

    def _confirm(self, prompt: str) -> bool:
        answer = prompt_yes_no(
            prompt,
            input_reader=self._input_reader,
            output_writer=self._output_writer,
        )
        return answer is True

    @staticmethod
    def _recovery_context(state: CatalogAgentState) -> RecoveryContext | None:
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

    def _display_transition(
        self,
        number: int,
        state: CatalogAgentState,
        decision: CatalogDecision,
    ) -> None:
        self._output_writer("-" * 60)
        self._output_writer(f"Transition {number}")
        self._output_writer("-" * 60)
        self._output_writer(f"Current status: {state.status.value}")
        self._output_writer(f"Current stage: {state.stage.value}")
        self._output_writer(f"Decision: {decision.decision_type.value}")
        self._output_writer(f"Reason: {decision.reason_code.value}")
        if decision.selected_issue_code:
            self._output_writer(f"Selected issue: {decision.selected_issue_code}")
            self._output_writer(f"Field: {decision.selected_issue_field}")
        if decision.action_request is not None:
            action = decision.action_request
            self._output_writer(f"Selected action: {action.action.value}")
            self._output_writer(f"Attempt: {action.attempt_number}")
        if state.candidate_profile is not None:
            requirements = [
                requirement.canonical_name
                for requirement in state.candidate_profile.requirements
            ]
            unresolved = state.candidate_profile.unresolved_skills
        else:
            requirements = (
                [item.raw_skill for item in state.extraction_result.requirements]
                if state.extraction_result is not None
                else []
            )
            unresolved = (
                state.normalization_result.unresolved_skills
                if state.normalization_result is not None
                else []
            )
        self._output_writer(
            "Current requirements: "
            + (", ".join(requirements) if requirements else "none")
        )
        self._output_writer(
            "Unresolved requirements: "
            + (", ".join(unresolved) if unresolved else "none")
        )
        if state.pending_clarification is not None:
            self._output_writer(
                f"Pending clarification: {state.pending_clarification.clarification_id}"
            )
        if state.escalation is not None:
            self._output_writer(
                f"Escalation: {state.escalation.escalation_id} "
                f"({state.escalation.issue_code})"
            )

    def _display_new_state(self, state: CatalogAgentState) -> None:
        self._output_writer(f"New status: {state.status.value}")
        self._output_writer(f"New stage: {state.stage.value}")
        self._output_writer(f"State version: {state.state_version}")
        if self._show_state:
            safe = redact_sensitive(state.model_dump(mode="json"))
            self._output_writer(json.dumps(safe, indent=2, ensure_ascii=False))

    def _display_summary(self, state: CatalogAgentState, transitions: int) -> None:
        recovery_attempts = sum(state.retry_counts.values())
        clarifications_requested = sum(
            entry.produced_clarification_request for entry in state.recovery_history
        )
        escalations_created = sum(
            entry.produced_escalation for entry in state.recovery_history
        )
        unresolved = (
            state.candidate_profile.unresolved_skills
            if state.candidate_profile is not None
            else state.normalization_result.unresolved_skills
            if state.normalization_result is not None
            else []
        )
        self._output_writer("=" * 60)
        self._output_writer("Scenario Summary")
        self._output_writer("=" * 60)
        self._output_writer(f"Request ID: {state.request.request_id}")
        self._output_writer(f"Final status: {state.status.value}")
        self._output_writer(f"Final stage: {state.stage.value}")
        self._output_writer(f"State version: {state.state_version}")
        self._output_writer(f"Total transitions: {transitions}")
        self._output_writer(f"Recovery attempts: {recovery_attempts}")
        self._output_writer(f"Clarifications requested: {clarifications_requested}")
        self._output_writer(
            f"Clarifications applied: {len(state.clarification_history)}"
        )
        self._output_writer(f"Escalations created: {escalations_created}")
        self._output_writer(
            f"Escalations reviewed: {len(state.escalation_review_history)}"
        )
        validation = (
            "valid"
            if state.validation_result is not None and state.validation_result.valid
            else "invalid"
            if state.validation_result is not None
            else "not available"
        )
        self._output_writer(f"Validation result: {validation}")
        self._output_writer(
            "Remaining unresolved requirements: "
            + (", ".join(unresolved) if unresolved else "none")
        )
        if state.status is CatalogStatus.COMPLETED and state.candidate_profile:
            self._output_writer("Skill | Importance | Required level")
            for requirement in state.candidate_profile.requirements:
                level = (
                    str(int(requirement.required_level))
                    if requirement.required_level is not None
                    else "none"
                )
                self._output_writer(
                    f"{requirement.canonical_name} | "
                    f"{requirement.importance.value} | {level}"
                )
        if state.status is CatalogStatus.ESCALATED:
            self._output_writer("Project was not completed or published.")
            self._output_writer("Human/taxonomy review is still required.")
        if self._audit_sink.events:
            self._output_writer("Audit events:")
            self._output_writer("Time | Actor | Role | Operation | Target | Outcome")
            for event in self._audit_sink.events:
                self._output_writer(
                    f"{event.occurred_at.isoformat()} | {event.actor_id} | "
                    f"{event.role.value} | {event.operation} | "
                    f"{event.target_id} | {event.outcome}"
                )

    def _credentials_missing(self) -> None:
        self._output_writer("Admin credentials are not configured.")
        self._output_writer("Generate them with:")
        self._output_writer("  python -m project_catalog_agent.admin_setup")
