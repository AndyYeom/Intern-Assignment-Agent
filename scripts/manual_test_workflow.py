"""Run the six controlled end-to-end workflow smoke scenarios."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from project_catalog_agent.admin import AdminRole
from project_catalog_agent.catalog.contracts import (
    ClarificationResponse,
    CreateProjectRequest,
)
from project_catalog_agent.demo import DemoScenario
from project_catalog_agent.demo.scenarios import DemoScenarioBundle, scenario_bundle
from project_catalog_agent.persistence import (
    InMemoryProjectRepository,
    ProjectRepositoryError,
    StoredProject,
)
from project_catalog_agent.workflow import (
    CatalogWorkflowConfig,
    WorkflowOutcome,
    create_controlled_workflow,
    create_memory_checkpointer,
)

DEFAULT_CASES = Path("tests/manual/workflow_cases.json")


class _ControlledAuthorizer:
    def is_authorized(self, *, actor_id: str, required_role: AdminRole) -> bool:
        return actor_id == "clarifier" and required_role is AdminRole.CLARIFIER


class _FailingRepository:
    def create(self, project: StoredProject) -> StoredProject:
        del project
        raise ProjectRepositoryError("controlled repository failure")

    def get_by_request_id(self, request_id: str) -> StoredProject | None:
        del request_id
        return None

    def get_by_project_id(self, project_id: str) -> StoredProject | None:
        del project_id
        return None

    def list_projects(self) -> tuple[StoredProject, ...]:
        return ()


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=int, choices=range(0, 7))
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    return parser.parse_args(argv)


def _valid_bundle(case_id: str) -> DemoScenarioBundle:
    request = CreateProjectRequest(
        request_id=case_id,
        project_name="Python Reporting Application",
        project_description="Build a reporting application using Python.",
    )
    return scenario_bundle(DemoScenario.CUSTOM, request=request)


async def _run_case(index: int) -> tuple[bool, dict[str, object]]:
    repository: InMemoryProjectRepository | _FailingRepository
    config = CatalogWorkflowConfig()
    if index == 1:
        bundle = _valid_bundle("E2E-001")
        repository = InMemoryProjectRepository()
    elif index == 2:
        bundle = scenario_bundle(DemoScenario.AMBIGUOUS_CLOUD)
        repository = InMemoryProjectRepository()
    elif index == 3:
        bundle = scenario_bundle(DemoScenario.UNMAPPED_SKILL)
        repository = InMemoryProjectRepository()
    elif index == 4:
        bundle = _valid_bundle("E2E-004")
        repository = InMemoryProjectRepository()
    elif index == 5:
        bundle = _valid_bundle("E2E-005")
        repository = _FailingRepository()
    else:
        bundle = _valid_bundle("E2E-006")
        repository = InMemoryProjectRepository()
        config = CatalogWorkflowConfig(max_transitions=2)
    workflow = create_controlled_workflow(
        bundle=bundle,
        repository=repository,
        checkpointer=create_memory_checkpointer(),
        admin_authorizer=_ControlledAuthorizer(),
        config=config,
        project_id_factory=lambda: f"PRJ-{bundle.request.request_id}",
    )
    first = await workflow.start(bundle.request)
    result = first
    if index == 2:
        pending = first.pending_clarification
        if pending is None:
            return False, {"outcome": first.outcome.value}
        result = await workflow.resume_clarification(
            thread_id=first.thread_id,
            response=ClarificationResponse(
                request_id=first.request_id,
                clarification_id=pending.clarification_id,
                answered_by="clarifier",
                selected_value=pending.options[0].value,
                submitted_at=datetime.now(UTC),
            ),
        )
    elif index == 4:
        workflow = create_controlled_workflow(
            bundle=bundle,
            repository=repository,
            checkpointer=create_memory_checkpointer(),
            admin_authorizer=_ControlledAuthorizer(),
            config=config,
            project_id_factory=lambda: "UNUSED-RETRY-ID",
        )
        result = await workflow.start(bundle.request)
    expected = {
        1: WorkflowOutcome.COMPLETED,
        2: WorkflowOutcome.COMPLETED,
        3: WorkflowOutcome.ESCALATED,
        4: WorkflowOutcome.COMPLETED,
        5: WorkflowOutcome.PERMANENT_FAILURE,
        6: WorkflowOutcome.PERMANENT_FAILURE,
    }[index]
    project_count = len(repository.list_projects())
    passed = result.outcome is expected
    if index in {1, 2, 4}:
        passed = passed and project_count == 1
    else:
        passed = passed and project_count == 0
    return passed, {
        "outcome": result.outcome.value,
        "thread_id": result.thread_id,
        "project_id": result.stored_project_id,
        "project_count": project_count,
        "error_code": result.error.code if result.error else None,
    }


async def _run(indices: list[int], descriptions: list[str]) -> bool:
    results: list[bool] = []
    for index in indices:
        passed, actual = await _run_case(index)
        print(f"\n--- {index}. {descriptions[index - 1]} ---")
        print(json.dumps(actual, indent=2))
        print(f"Result: {'PASS' if passed else 'FAIL'}")
        results.append(passed)
    print(f"\nPassed: {sum(results)}/{len(results)}")
    return all(results)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    payload = json.loads(arguments.cases.read_text(encoding="utf-8"))
    descriptions = [str(item["scenario"]) for item in payload["test_cases"]]
    selected = arguments.case
    if selected is None:
        print("0. Run all cases")
        for index, description in enumerate(descriptions, start=1):
            print(f"{index}. {description}")
        selected = int(input("Select a case: ").strip())
    indices = list(range(1, 7)) if selected == 0 else [selected]
    return 0 if asyncio.run(_run(indices, descriptions)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
