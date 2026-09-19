"""Tests for deterministic application of admin clarification answers."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from project_catalog_agent.agent import (
    CatalogStateUpdater,
    ClarificationResponseProcessor,
)
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ClarificationApplicationStatus,
    ClarificationHistoryEntry,
    ClarificationOption,
    ClarificationRequest,
    ClarificationResponse,
    CreateProjectRequest,
    ExtractedRequirement,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyCandidate,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
    ValidationResult,
)
from project_catalog_agent.errors import InvalidStateTransitionError
from project_catalog_agent.profile import ProjectProfileBuilder
from project_catalog_agent.taxonomy import JsonTaxonomyRepository


class FixedAuthorizer:
    """Authorize only explicitly configured actor IDs."""

    def __init__(self, *allowed: str) -> None:
        self.allowed = set(allowed)

    def is_authorized(self, *, actor_id: str, required_role: object) -> bool:
        del required_role
        return actor_id in self.allowed


def extraction() -> RequirementExtractionResult:
    """Create resolved and ambiguous controlled requirements."""
    return RequirementExtractionResult(
        project_summary="Build a Python service on a cloud platform.",
        requirements=[
            ExtractedRequirement(
                raw_skill="Python",
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=None,
                confidence=0.55,
                evidence_text="Python is required.",
                decision_basis="Python is mandatory.",
            ),
            ExtractedRequirement(
                raw_skill="Cloud platform",
                importance=RequirementImportance.PREFERRED,
                required_level=ProficiencyLevel.ENTRY,
                confidence=0.7,
                evidence_text="Use AWS or another cloud platform.",
                decision_basis="A cloud platform is requested.",
            ),
        ],
    )


def normalization() -> TaxonomyNormalizationResult:
    """Create one resolved and one needs-review mapping."""
    return TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill="Python",
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id="python",
                canonical_skill="Python",
                decision_basis="Exact match.",
            ),
            TaxonomyMapping(
                source_requirement_index=1,
                raw_skill="Cloud platform",
                status=MappingStatus.NEEDS_REVIEW,
                match_method=MatchMethod.UNRESOLVED,
                candidates=[
                    TaxonomyCandidate(skill_id="aws", canonical_name="AWS"),
                    TaxonomyCandidate(skill_id="gcp-azure", canonical_name="GCP/Azure"),
                ],
                decision_basis="Multiple cloud candidates remain.",
            ),
        ],
        unresolved_skills=["Cloud platform"],
    )


def pending_state(
    *,
    issue_code: str = "MISSING_REQUIRED_LEVEL",
    field: str = "requirements[0].required_level",
    options: list[ClarificationOption] | None = None,
    allow_free_text: bool = False,
    clarification_id: str = "clarification-001",
    history: list[ClarificationHistoryEntry] | None = None,
) -> CatalogAgentState:
    """Create a valid paused state without invoking a workflow."""
    request = CreateProjectRequest(
        request_id="CLR-001",
        project_name="Clarification Test",
        project_description=(
            "Python is required. Use AWS or another cloud platform. "
            "Exact verified evidence."
        ),
    )
    extracted = extraction()
    normalized = normalization()
    profile = ProjectProfileBuilder().build(
        request=request,
        extraction=extracted,
        normalization=normalized,
    )
    clarification = ClarificationRequest(
        clarification_id=clarification_id,
        request_id=request.request_id,
        issue_code=issue_code,
        field=field,
        question="Which verified value should be used?",
        options=options
        if options is not None
        else [
            ClarificationOption(value="1", label="Entry"),
            ClarificationOption(value="2", label="Intermediate"),
            ClarificationOption(value="3", label="Advanced"),
        ],
        allow_free_text=allow_free_text,
    )
    return CatalogAgentState(
        request=request,
        status=CatalogStatus.AWAITING_CLARIFICATION,
        stage=CatalogStage.AWAITING_CLARIFICATION,
        extraction_result=extracted,
        normalization_result=normalized,
        candidate_profile=profile,
        validation_result=ValidationResult(valid=False, issues=[]),
        pending_clarification=clarification,
        clarification_history=history or [],
        state_version=7,
    )


def response(
    *,
    selected_value: str | None = "2",
    free_text: str | None = None,
    request_id: str = "CLR-001",
    clarification_id: str = "clarification-001",
    answered_by: str = "admin-1",
) -> ClarificationResponse:
    """Create one valid answer."""
    return ClarificationResponse(
        request_id=request_id,
        clarification_id=clarification_id,
        answered_by=answered_by,
        selected_value=selected_value,
        free_text=free_text,
        submitted_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
    )


def processor(*allowed: str) -> ClarificationResponseProcessor:
    """Create a processor with the packaged read-only taxonomy."""
    return ClarificationResponseProcessor(
        taxonomy_repository=JsonTaxonomyRepository(),
        state_updater=CatalogStateUpdater(),
        admin_authorizer=FixedAuthorizer(*allowed),
    )


def assert_rejected(
    result_status: ClarificationApplicationStatus,
    error_code: str | None,
    expected: str,
) -> None:
    assert result_status is ClarificationApplicationStatus.REJECTED
    assert error_code == expected


def test_no_pending_clarification_is_rejected() -> None:
    state = CatalogAgentState(
        request=pending_state().request,
        status=CatalogStatus.PROCESSING,
        stage=CatalogStage.RECEIVED,
    )
    result = processor("admin-1").apply(state=state, response=response())

    assert_rejected(result.status, result.error_code, "NO_PENDING_CLARIFICATION")
    assert result.updated_state is None


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (response(request_id="OTHER"), "REQUEST_ID_MISMATCH"),
        (
            response(clarification_id="another-clarification"),
            "CLARIFICATION_ID_MISMATCH",
        ),
        (response(answered_by="stranger"), "UNAUTHORIZED_RESPONDENT"),
    ],
)
def test_identity_and_authorization_rejections_do_not_change_state(
    answer: ClarificationResponse, code: str
) -> None:
    state = pending_state()
    before = state.model_dump_json()
    result = processor("admin-1").apply(state=state, response=answer)

    assert_rejected(result.status, result.error_code, code)
    assert state.model_dump_json() == before


def test_replay_is_rejected_before_authorization() -> None:
    entry = ClarificationHistoryEntry(
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
    state = pending_state(history=[entry])
    result = processor().apply(state=state, response=response())

    assert_rejected(result.status, result.error_code, "CLARIFICATION_ALREADY_APPLIED")


def test_missing_level_updates_extraction_and_invalidates_downstream() -> None:
    state = pending_state()
    original_normalization = state.normalization_result
    result = processor("admin-1").apply(state=state, response=response())

    assert result.status is ClarificationApplicationStatus.APPLIED
    assert result.updated_state is not None
    updated = result.updated_state
    assert updated.extraction_result is not None
    assert updated.extraction_result.requirements[0].required_level == 2
    assert updated.extraction_result.requirements[1] == extraction().requirements[1]
    assert updated.normalization_result is None
    assert updated.candidate_profile is None
    assert updated.validation_result is None
    assert updated.pending_clarification is None
    assert updated.status is CatalogStatus.PROCESSING
    assert updated.stage is CatalogStage.EXTRACTED
    assert updated.state_version == state.state_version + 1
    assert state.normalization_result == original_normalization


def test_applied_history_is_compact_ordered_and_serializable() -> None:
    result = processor("admin-1").apply(state=pending_state(), response=response())
    assert result.updated_state is not None
    history = result.updated_state.clarification_history

    assert len(history) == 1
    assert history[0].sequence == 1
    assert history[0].answered_by == "admin-1"
    assert history[0].accepted_value == "2"
    assert "admin-1" not in result.updated_state.request.project_description
    assert (
        CatalogAgentState.model_validate_json(result.updated_state.model_dump_json())
        == result.updated_state
    )


def test_needs_review_selection_resolves_known_taxonomy_skill() -> None:
    options = [
        ClarificationOption(value="aws", label="AWS", skill_id="aws"),
        ClarificationOption(value="gcp-azure", label="GCP/Azure", skill_id="gcp-azure"),
    ]
    state = pending_state(
        issue_code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        options=options,
    )
    result = processor("admin-1").apply(
        state=state, response=response(selected_value="aws")
    )

    assert result.updated_state is not None
    updated = result.updated_state
    assert updated.normalization_result is not None
    mapping = updated.normalization_result.mappings[1]
    assert mapping.status is MappingStatus.RESOLVED
    assert mapping.match_method is MatchMethod.CLARIFIED
    assert mapping.skill_id == "aws"
    assert mapping.canonical_skill == "AWS"
    assert mapping.candidates == []
    assert updated.normalization_result.unresolved_skills == []
    assert updated.extraction_result == state.extraction_result
    assert updated.stage is CatalogStage.NORMALIZED


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("AWS", "INVALID_SELECTED_OPTION"),
        ("invented", "UNKNOWN_TAXONOMY_SKILL"),
    ],
)
def test_taxonomy_selection_requires_exact_safe_option(
    answer: str, expected: str
) -> None:
    options = [
        ClarificationOption(value="aws", label="AWS", skill_id="aws"),
        ClarificationOption(value="invented", label="Invented", skill_id="invented"),
    ]
    state = pending_state(
        issue_code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        options=options,
    )
    result = processor("admin-1").apply(
        state=state, response=response(selected_value=answer)
    )

    assert_rejected(result.status, result.error_code, expected)


def test_taxonomy_free_text_is_not_supported() -> None:
    state = pending_state(
        issue_code="UNMAPPED_REQUIREMENT",
        field="unresolved_requirements[0]",
        options=[],
        allow_free_text=True,
    )
    result = processor("admin-1").apply(
        state=state,
        response=response(selected_value=None, free_text="AWS"),
    )

    assert_rejected(result.status, result.error_code, "UNSUPPORTED_CLARIFICATION")


def test_inactive_taxonomy_option_is_rejected(tmp_path: Path) -> None:
    taxonomy_path = tmp_path / "taxonomy.json"
    taxonomy_path.write_text(
        json.dumps(
            {
                "taxonomy_version": "test",
                "level_scale": "1-3",
                "notes": "Controlled inactive skill.",
                "skills": [
                    {
                        "id": "retired-cloud",
                        "name": "Retired Cloud",
                        "category": "Cloud",
                        "active": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    controlled_processor = ClarificationResponseProcessor(
        taxonomy_repository=JsonTaxonomyRepository(taxonomy_path),
        state_updater=CatalogStateUpdater(),
        admin_authorizer=FixedAuthorizer("admin-1"),
    )
    state = pending_state(
        issue_code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        options=[
            ClarificationOption(
                value="retired-cloud",
                label="Retired Cloud",
                skill_id="retired-cloud",
            )
        ],
    )

    result = controlled_processor.apply(
        state=state, response=response(selected_value="retired-cloud")
    )

    assert_rejected(result.status, result.error_code, "UNKNOWN_TAXONOMY_SKILL")


def test_option_containing_invalid_level_is_rejected() -> None:
    state = pending_state(
        options=[ClarificationOption(value="9", label="Invalid level")]
    )
    result = processor("admin-1").apply(
        state=state, response=response(selected_value="9")
    )

    assert_rejected(result.status, result.error_code, "INVALID_SELECTED_OPTION")


@pytest.mark.parametrize(
    ("selected", "expected_importance", "remaining"),
    [
        ("required", RequirementImportance.HARD_REQUIREMENT, 2),
        ("preferred", RequirementImportance.PREFERRED, 2),
        ("learning_opportunity", RequirementImportance.LEARNING_OPPORTUNITY, 2),
        ("not_a_requirement", None, 1),
    ],
)
def test_low_confidence_answer_changes_importance_without_inflating_confidence(
    selected: str,
    expected_importance: RequirementImportance | None,
    remaining: int,
) -> None:
    options = [
        ClarificationOption(value=value, label=value.replace("_", " ").title())
        for value in (
            "required",
            "preferred",
            "learning_opportunity",
            "not_a_requirement",
        )
    ]
    state = pending_state(
        issue_code="LOW_EXTRACTION_CONFIDENCE",
        field="requirements[0].confidence",
        options=options,
    )
    result = processor("admin-1").apply(
        state=state, response=response(selected_value=selected)
    )

    assert result.updated_state is not None
    extracted = result.updated_state.extraction_result
    assert extracted is not None
    assert len(extracted.requirements) == remaining
    if expected_importance is not None:
        assert extracted.requirements[0].importance is expected_importance
        assert extracted.requirements[0].confidence == 0.55


def test_exact_verbatim_evidence_is_applied() -> None:
    state = pending_state(
        issue_code="EVIDENCE_NOT_VERBATIM",
        field="requirements[0].evidence_text",
        options=[],
        allow_free_text=True,
    )
    result = processor("admin-1").apply(
        state=state,
        response=response(selected_value=None, free_text="Exact verified evidence."),
    )

    assert result.updated_state is not None
    extracted = result.updated_state.extraction_result
    assert extracted is not None
    assert extracted.requirements[0].evidence_text == "Exact verified evidence."


def test_nonverbatim_evidence_is_rejected() -> None:
    state = pending_state(
        issue_code="EVIDENCE_NOT_VERBATIM",
        field="requirements[0].evidence_text",
        options=[],
        allow_free_text=True,
    )
    result = processor("admin-1").apply(
        state=state,
        response=response(selected_value=None, free_text="Paraphrased evidence."),
    )

    assert_rejected(result.status, result.error_code, "EVIDENCE_NOT_VERBATIM")


def test_provenance_evidence_target_updates_the_source_requirement() -> None:
    state = pending_state(
        issue_code="PROVENANCE_EVIDENCE_NOT_VERBATIM",
        field="requirements[0].provenance[0].evidence_text",
        options=[],
        allow_free_text=True,
    )
    result = processor("admin-1").apply(
        state=state,
        response=response(selected_value=None, free_text="Exact verified evidence."),
    )

    assert result.updated_state is not None
    extracted = result.updated_state.extraction_result
    assert extracted is not None
    assert extracted.requirements[0].evidence_text == "Exact verified evidence."
    assert extracted.requirements[1] == extraction().requirements[1]


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("requirements[-1].required_level", "INVALID_TARGET_FIELD"),
        ("requirements[99].required_level", "TARGET_NOT_FOUND"),
        ("__class__.__dict__", "INVALID_TARGET_FIELD"),
    ],
)
def test_unsafe_or_out_of_range_target_is_rejected(field: str, code: str) -> None:
    state = pending_state(field=field)
    result = processor("admin-1").apply(state=state, response=response())

    assert_rejected(result.status, result.error_code, code)


def test_repeated_application_from_same_input_is_deterministic() -> None:
    state = pending_state()
    answer = response()
    repository = JsonTaxonomyRepository()
    controlled_processor = ClarificationResponseProcessor(
        taxonomy_repository=repository,
        state_updater=CatalogStateUpdater(),
        admin_authorizer=FixedAuthorizer("admin-1"),
    )
    state_before = state.model_dump_json()
    answer_before = answer.model_dump_json()
    taxonomy_before = repository.list_skills()
    first = controlled_processor.apply(state=state, response=answer)
    second = controlled_processor.apply(state=state, response=answer)

    assert first == second
    assert state.model_dump_json() == state_before
    assert answer.model_dump_json() == answer_before
    assert repository.list_skills() == taxonomy_before


def test_history_sequence_continues_monotonically() -> None:
    older = ClarificationHistoryEntry(
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
    state = pending_state(
        clarification_id="clarification-002",
        history=[older],
    )
    result = processor("admin-1").apply(
        state=state,
        response=response(clarification_id="clarification-002"),
    )

    assert result.updated_state is not None
    assert [entry.sequence for entry in result.updated_state.clarification_history] == [
        1,
        2,
    ]


@pytest.mark.parametrize("artifact_count", [0, 2])
def test_state_updater_requires_exactly_one_clarified_artifact(
    artifact_count: int,
) -> None:
    state = pending_state()
    history = ClarificationHistoryEntry(
        sequence=1,
        clarification_id="clarification-001",
        issue_code="MISSING_REQUIRED_LEVEL",
        field="requirements[0].required_level",
        answered_by="admin-1",
        answer_type="selected_value",
        accepted_value="2",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        applied_stage=CatalogStage.EXTRACTED,
    )
    with pytest.raises(InvalidStateTransitionError):
        if artifact_count == 2:
            CatalogStateUpdater().apply_clarification_update(
                state,
                history_entry=history,
                updated_extraction=extraction(),
                updated_normalization=normalization(),
            )
        else:
            CatalogStateUpdater().apply_clarification_update(
                state,
                history_entry=history,
            )
