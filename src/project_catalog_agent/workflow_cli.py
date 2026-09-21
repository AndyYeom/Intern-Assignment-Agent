"""Interactive durable CLI for the resumable Project Catalog workflow."""

import argparse
import asyncio
import getpass
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from project_catalog_agent.admin import (
    AdminRole,
    AuthenticationStatus,
    InMemoryAuditSink,
)
from project_catalog_agent.admin.terminal import (
    TerminalAdminLogin,
    TerminalEscalationHandler,
)
from project_catalog_agent.catalog.contracts import (
    ClarificationResponse,
    CreateProjectRequest,
)
from project_catalog_agent.demo.input import prompt_bounded_text, prompt_menu_choice
from project_catalog_agent.workflow import (
    CatalogWorkflowResult,
    WorkflowOutcome,
    open_local_sqlite_workflow,
)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse local paths without accepting credential values on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-database",
        type=Path,
        default=Path("catalog_projects.sqlite3"),
    )
    parser.add_argument(
        "--checkpoint-database",
        type=Path,
        default=Path("catalog_workflows.sqlite3"),
    )
    parser.add_argument("--max-transitions", type=int, default=30)
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    if args.max_transitions < 1:
        raise SystemExit("--max-transitions must be at least one")
    from project_catalog_agent.workflow import CatalogWorkflowConfig

    async with open_local_sqlite_workflow(
        project_database=args.project_database,
        checkpoint_database=args.checkpoint_database,
        config=CatalogWorkflowConfig(max_transitions=args.max_transitions),
    ) as runtime:
        login = TerminalAdminLogin(
            authenticator=runtime.authenticator,
            password_reader=getpass.getpass,
        )
        escalation_handler = TerminalEscalationHandler(
            login=login,
            processor=runtime.escalation_processor,
            audit_sink=InMemoryAuditSink(),
        )
        while True:
            _menu()
            choice = prompt_menu_choice(
                "Select an option: ",
                {str(index): str(index) for index in range(1, 7)},
            )
            if choice in {None, "6"}:
                print("Workflow CLI closed.")
                return 0
            try:
                if choice == "1":
                    await _submit(runtime.workflow)
                elif choice == "2":
                    await _resume(runtime.workflow, login)
                elif choice == "3":
                    await _view(runtime.workflow)
                elif choice == "4":
                    await _review(runtime.workflow, escalation_handler)
                elif choice == "5":
                    _list_projects(runtime.project_repository.list_projects())
            except (EOFError, KeyboardInterrupt):
                print("Operation cancelled.")
            except Exception as error:
                print(f"Operation failed safely: {type(error).__name__}")


async def _submit(workflow: object) -> None:
    from project_catalog_agent.workflow import CatalogWorkflow

    facade = workflow if isinstance(workflow, CatalogWorkflow) else None
    if facade is None:
        raise TypeError("workflow facade is unavailable")
    name = prompt_bounded_text("Project name: ", max_length=200)
    if name is None:
        return
    description = prompt_bounded_text("Project description: ", max_length=20_000)
    if description is None:
        return
    request = CreateProjectRequest(
        request_id=f"REQ-{uuid4().hex.upper()}",
        project_name=name,
        project_description=description,
    )
    _display(await facade.start(request))


async def _resume(workflow: object, login: TerminalAdminLogin) -> None:
    from project_catalog_agent.workflow import CatalogWorkflow

    if not isinstance(workflow, CatalogWorkflow):
        raise TypeError("workflow facade is unavailable")
    thread_id = prompt_bounded_text("Thread/request ID: ", max_length=200)
    if thread_id is None:
        return
    state = await workflow.get_state(thread_id=thread_id)
    pending = state.pending_clarification
    if pending is None:
        print("This workflow is not awaiting clarification.")
        return
    authentication = login.login(required_role=AdminRole.CLARIFIER)
    if authentication.status is not AuthenticationStatus.AUTHENTICATED:
        print("Clarification was not resumed.")
        return
    print(pending.question)
    selected_value: str | None = None
    free_text: str | None = None
    if pending.options:
        for index, option in enumerate(pending.options, start=1):
            print(f"{index}. {option.label}")
        selected = prompt_menu_choice(
            "Select an answer: ",
            {str(index): str(index) for index in range(1, len(pending.options) + 1)},
        )
        if selected is None:
            return
        selected_value = pending.options[int(selected) - 1].value
    elif pending.allow_free_text:
        free_text = prompt_bounded_text("Answer: ", max_length=2_000)
        if free_text is None:
            return
    else:
        print("No supported clarification answer is available.")
        return
    _display(
        await workflow.resume_clarification(
            thread_id=thread_id,
            response=ClarificationResponse(
                request_id=state.request.request_id,
                clarification_id=pending.clarification_id,
                answered_by=authentication.actor_id or "",
                selected_value=selected_value,
                free_text=free_text,
                submitted_at=datetime.now(UTC),
            ),
        )
    )


async def _view(workflow: object) -> None:
    from project_catalog_agent.workflow import CatalogWorkflow

    if not isinstance(workflow, CatalogWorkflow):
        raise TypeError("workflow facade is unavailable")
    thread_id = prompt_bounded_text("Thread/request ID: ", max_length=200)
    if thread_id is None:
        return
    state = await workflow.get_state(thread_id=thread_id)
    print(state.model_dump_json(indent=2))


async def _review(
    workflow: object,
    handler: TerminalEscalationHandler,
) -> None:
    from project_catalog_agent.workflow import CatalogWorkflow

    if not isinstance(workflow, CatalogWorkflow):
        raise TypeError("workflow facade is unavailable")
    thread_id = prompt_bounded_text("Thread/request ID: ", max_length=200)
    if thread_id is None:
        return
    state = await workflow.get_state(thread_id=thread_id)
    result = handler.handle(state=state)
    if result.updated_state is not None:
        await workflow.record_escalation_review(
            thread_id=thread_id,
            updated_state=result.updated_state,
        )
    print(f"Escalation review: {result.status.value}")


def _display(result: CatalogWorkflowResult) -> None:
    print(f"Thread ID: {result.thread_id}")
    print(f"Outcome: {result.outcome.value}")
    if result.outcome is WorkflowOutcome.COMPLETED:
        print(f"Published project ID: {result.stored_project_id}")
    elif result.pending_clarification is not None:
        print(f"Clarification: {result.pending_clarification.question}")
    elif result.escalation is not None:
        print(f"Escalation: {result.escalation.reason}")
    elif result.error is not None:
        print(f"Error: {result.error.code}")


def _list_projects(projects: tuple[object, ...]) -> None:
    if not projects:
        print("No published projects.")
        return
    for item in projects:
        from project_catalog_agent.persistence import StoredProject

        if isinstance(item, StoredProject):
            print(
                f"{item.project_id} | {item.request_id} | "
                f"{item.project_profile.project_name}"
            )


def _menu() -> None:
    print("\nProject Catalog Workflow")
    print("1. Submit a project")
    print("2. Resume pending clarification")
    print("3. View workflow state")
    print("4. Review escalation")
    print("5. List published projects")
    print("6. Exit")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the durable local workflow CLI."""
    return asyncio.run(_run(parse_arguments(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
