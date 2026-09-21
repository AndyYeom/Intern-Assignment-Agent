"""Execute the supplied CLR-001 through CLR-012 manual scenarios."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ClarificationHistoryEntry,
    ClarificationOption,
    ClarificationResponse,
)
from tests.agent.test_clarification import pending_state, processor, response

CASES_PATH = Path(__file__).parents[1] / "manual" / "clarification_cases.json"
CASES: list[dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))[
    "test_cases"
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["case_id"]))
def test_supplied_clarification_scenario(case: dict[str, Any]) -> None:
    scenario = str(case["scenario"])
    if scenario == "both_answer_forms":
        with pytest.raises(ValidationError):
            ClarificationResponse(
                request_id="CLR-001",
                clarification_id="clarification-001",
                answered_by="admin-1",
                selected_value="2",
                free_text="Exact verified evidence.",
                submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        return

    state = pending_state()
    answer = response()
    allowed = ("admin-1",)

    if scenario == "needs_review_aws":
        state = pending_state(
            issue_code="NEEDS_REVIEW_REQUIREMENT",
            field="unresolved_requirements[0]",
            options=[
                ClarificationOption(value="aws", label="AWS", skill_id="aws"),
                ClarificationOption(
                    value="gcp-azure", label="GCP/Azure", skill_id="gcp-azure"
                ),
            ],
        )
        answer = response(selected_value="aws")
    elif scenario == "unknown_option":
        answer = response(selected_value="9")
    elif scenario == "wrong_clarification_id":
        answer = response(clarification_id="wrong")
    elif scenario == "wrong_request_id":
        answer = response(request_id="wrong")
    elif scenario == "unauthorized":
        allowed = ()
    elif scenario == "no_pending":
        state = CatalogAgentState(
            request=state.request,
            status=CatalogStatus.PROCESSING,
            stage=CatalogStage.RECEIVED,
        )
    elif scenario == "replay":
        state = pending_state(
            history=[
                ClarificationHistoryEntry(
                    sequence=1,
                    clarification_id="clarification-001",
                    issue_code="OLDER_ISSUE",
                    field="requirements[0]",
                    answered_by="admin-1",
                    answer_type="selected_value",
                    accepted_value="1",
                    submitted_at=datetime(2025, 1, 1, tzinfo=UTC),
                    applied_stage=CatalogStage.EXTRACTED,
                )
            ]
        )
    elif scenario in {"verbatim_evidence", "paraphrased_evidence"}:
        state = pending_state(
            issue_code="EVIDENCE_NOT_VERBATIM",
            field="requirements[0].evidence_text",
            options=[],
            allow_free_text=True,
        )
        evidence = (
            "Exact verified evidence."
            if scenario == "verbatim_evidence"
            else "Paraphrased evidence."
        )
        answer = response(selected_value=None, free_text=evidence)
    elif scenario == "free_text_taxonomy_skill":
        state = pending_state(
            issue_code="UNMAPPED_REQUIREMENT",
            field="unresolved_requirements[0]",
            options=[],
            allow_free_text=True,
        )
        answer = response(selected_value=None, free_text="New invented skill")

    result = processor(*allowed).apply(state=state, response=answer)

    assert result.status.value == case["expected_status"]
    assert result.error_code == case.get("expected_error_code")
    if expected_stage := case.get("expected_stage"):
        assert result.updated_state is not None
        assert result.updated_state.stage.value == expected_stage
