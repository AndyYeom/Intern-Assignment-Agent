"""Tests for guarded, bounded recovery-action execution."""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import NoReturn, ParamSpec

import pytest
from pydantic import ValidationError

from project_catalog_agent.actions import RecoveryActionExecutor
from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    IssueCategory,
    IssueSeverity,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryContext,
    RecoveryStatus,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyCandidate,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
    ValidationIssue,
    ValidationResult,
)
from project_catalog_agent.errors import (
    ProjectProfileBuildError,
    RequirementExtractionError,
)
from project_catalog_agent.profile import ProjectProfileBuilder
from project_catalog_agent.taxonomy import (
    JsonTaxonomyRepository,
    TaxonomyNormalizationError,
)

P = ParamSpec("P")


def async_test(function: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Run an async test without adding a test-runner plugin dependency."""

    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return wrapper


def extraction(
    *, summary: str = "A controlled recovery project."
) -> RequirementExtractionResult:
    """Return extraction data with one resolved and one ambiguous skill."""
    return RequirementExtractionResult(
        project_summary=summary,
        requirements=[
            ExtractedRequirement(
                raw_skill="Python",
                importance=RequirementImportance.HARD_REQUIREMENT,
                required_level=ProficiencyLevel.INTERMEDIATE,
                confidence=0.95,
                evidence_text="Python is required.",
                decision_basis="Python is mandatory.",
            ),
            ExtractedRequirement(
                raw_skill="Cloud platform",
                importance=RequirementImportance.PREFERRED,
                required_level=ProficiencyLevel.ENTRY,
                confidence=0.6,
                evidence_text="AWS or Azure experience is helpful.",
                decision_basis="A cloud provider is preferred.",
            ),
        ],
    )


def normalization(*, resolved_cloud: bool = False) -> TaxonomyNormalizationResult:
    """Return controlled complete normalization data."""
    cloud = (
        TaxonomyMapping(
            source_requirement_index=1,
            raw_skill="Cloud platform",
            status=MappingStatus.RESOLVED,
            match_method=MatchMethod.LLM_SELECTED,
            skill_id="aws",
            canonical_skill="AWS",
            match_score=0.8,
            decision_basis="AWS was selected from known candidates.",
        )
        if resolved_cloud
        else TaxonomyMapping(
            source_requirement_index=1,
            raw_skill="Cloud platform",
            status=MappingStatus.NEEDS_REVIEW,
            match_method=MatchMethod.UNRESOLVED,
            candidates=[
                TaxonomyCandidate(skill_id="aws", canonical_name="AWS"),
                TaxonomyCandidate(skill_id="gcp-azure", canonical_name="GCP/Azure"),
            ],
            decision_basis="More than one cloud platform is plausible.",
        )
    )
    return TaxonomyNormalizationResult(
        mappings=[
            TaxonomyMapping(
                source_requirement_index=0,
                raw_skill="Python",
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.EXACT,
                skill_id="python",
                canonical_skill="Python",
                decision_basis="Exact canonical match.",
            ),
            cloud,
        ],
        unresolved_skills=[] if resolved_cloud else ["Cloud platform"],
    )


def validation_issue(
    *,
    code: str = "TEST_ISSUE",
    field: str = "requirements[0]",
    actions: list[str] | None = None,
) -> ValidationIssue:
    """Build one controlled blocking issue."""
    return ValidationIssue(
        code=code,
        field=field,
        severity=IssueSeverity.BLOCKING,
        category=IssueCategory.CONFLICT,
        message="Controlled recovery issue.",
        resolvable_by=actions or ["rebuild_profile"],
    )


def recovery_context(
    issue: ValidationIssue, *, stale_profile: bool = False
) -> RecoveryContext:
    """Build all current artifacts for one recovery attempt."""
    request = CreateProjectRequest(
        request_id="REC-001",
        project_name="Recovery Test",
        project_description=("Python is required. AWS or Azure experience is helpful."),
    )
    extracted = extraction()
    normalized = normalization()
    profile = ProjectProfileBuilder().build(
        request=request,
        extraction=extracted,
        normalization=normalized,
    )
    if stale_profile:
        profile = profile.model_copy(update={"project_summary": "Stale summary."})
    return RecoveryContext(
        request=request,
        extraction_result=extracted,
        normalization_result=normalized,
        candidate_profile=profile,
        validation_result=ValidationResult(valid=False, issues=[issue]),
    )


class StubExtractor:
    """Return or raise one configured extraction response."""

    def __init__(
        self,
        response: RequirementExtractionResult,
        error: RequirementExtractionError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    async def extract(
        self, request: CreateProjectRequest
    ) -> RequirementExtractionResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response.model_copy(deep=True)


class StubNormalizer:
    """Return or raise one configured normalization response."""

    def __init__(
        self,
        response: TaxonomyNormalizationResult,
        error: TaxonomyNormalizationError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    async def normalize(
        self, extraction_result: RequirementExtractionResult
    ) -> TaxonomyNormalizationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response.model_copy(deep=True)


class CountingBuilder(ProjectProfileBuilder):
    """Track deterministic builder calls."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def build(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise ProjectProfileBuildError("controlled failure")
        return super().build(**kwargs)  # type: ignore[arg-type]


def executor(
    *,
    extracted: RequirementExtractionResult | None = None,
    normalized: TaxonomyNormalizationResult | None = None,
    extraction_error: RequirementExtractionError | None = None,
    normalization_error: TaxonomyNormalizationError | None = None,
    builder: CountingBuilder | None = None,
) -> tuple[RecoveryActionExecutor, StubExtractor, StubNormalizer, CountingBuilder]:
    """Construct an executor and observable service doubles."""
    extractor = StubExtractor(extracted or extraction(), extraction_error)
    normalizer = StubNormalizer(normalized or normalization(), normalization_error)
    profile_builder = builder or CountingBuilder()
    return (
        RecoveryActionExecutor(
            extractor=extractor,
            normalizer=normalizer,
            profile_builder=profile_builder,
            taxonomy_repository=JsonTaxonomyRepository(),
        ),
        extractor,
        normalizer,
        profile_builder,
    )


def action(
    issue: ValidationIssue, name: RecoveryActionName, **updates: object
) -> RecoveryActionRequest:
    """Build an action bound to an issue."""
    values: dict[str, object] = {
        "request_id": "REC-001",
        "action": name,
        "issue_code": issue.code,
        "issue_field": issue.field,
    }
    values.update(updates)
    return RecoveryActionRequest.model_validate(values)


@async_test
async def test_permission_guard_rejects_missing_issue_and_unlisted_action() -> None:
    issue = validation_issue()
    runner, extractor, normalizer, builder = executor()
    context = recovery_context(issue)

    missing = await runner.execute(
        action_request=RecoveryActionRequest(
            request_id="REC-001",
            action=RecoveryActionName.REBUILD_PROFILE,
            issue_code="OTHER_ISSUE",
            issue_field=issue.field,
        ),
        context=context,
    )
    forbidden = await runner.execute(
        action_request=action(issue, RecoveryActionName.ESCALATE),
        context=context,
    )

    assert missing.error_code == "ISSUE_NOT_FOUND"
    assert forbidden.error_code == "ACTION_NOT_PERMITTED"
    assert extractor.calls == normalizer.calls == builder.calls == 0


@async_test
async def test_request_id_mismatch_is_an_invalid_target() -> None:
    issue = validation_issue()
    runner, _, _, _ = executor()
    request = action(issue, RecoveryActionName.REBUILD_PROFILE).model_copy(
        update={"request_id": "REC-OTHER"}
    )

    result = await runner.execute(
        action_request=RecoveryActionRequest.model_validate(request.model_dump()),
        context=recovery_context(issue),
    )

    assert result.error_code == "INVALID_ACTION_TARGET"


@async_test
async def test_rebuild_profile_reports_changed_and_no_change() -> None:
    issue = validation_issue(actions=["rebuild_profile"])
    runner, _, _, builder = executor()

    changed = await runner.execute(
        action_request=action(issue, RecoveryActionName.REBUILD_PROFILE),
        context=recovery_context(issue, stale_profile=True),
    )
    unchanged = await runner.execute(
        action_request=action(issue, RecoveryActionName.REBUILD_PROFILE),
        context=recovery_context(issue),
    )

    assert changed.status is RecoveryStatus.SUCCEEDED
    assert changed.changed is True
    assert changed.candidate_profile is not None
    assert unchanged.status is RecoveryStatus.NO_CHANGE
    assert builder.calls == 2


@async_test
async def test_rebuild_profile_translates_known_failure() -> None:
    issue = validation_issue()
    runner, _, _, _ = executor(builder=CountingBuilder(fail=True))

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.REBUILD_PROFILE),
        context=recovery_context(issue),
    )

    assert result.error_code == "PROFILE_REBUILD_FAILED"


@async_test
async def test_reextract_runs_only_extractor_once_and_returns_complete_output() -> None:
    issue = validation_issue(
        code="LOW_EXTRACTION_CONFIDENCE",
        field="requirements[0].confidence",
        actions=["reextract_field"],
    )
    updated = extraction(summary="Updated extraction summary.")
    runner, extractor, normalizer, builder = executor(extracted=updated)

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.REEXTRACT_FIELD),
        context=recovery_context(issue),
    )

    assert result.status is RecoveryStatus.SUCCEEDED
    assert result.extraction_result == updated
    assert extractor.calls == 1
    assert normalizer.calls == builder.calls == 0


@async_test
async def test_reextract_reports_no_change_failure_and_invalid_target() -> None:
    issue = validation_issue(
        code="LOW_EXTRACTION_CONFIDENCE",
        field="requirements[0].confidence",
        actions=["reextract_field"],
    )
    runner, _, _, _ = executor()
    unchanged = await runner.execute(
        action_request=action(issue, RecoveryActionName.REEXTRACT_FIELD),
        context=recovery_context(issue),
    )
    failing, _, _, _ = executor(
        extraction_error=RequirementExtractionError("controlled")
    )
    failed = await failing.execute(
        action_request=action(issue, RecoveryActionName.REEXTRACT_FIELD),
        context=recovery_context(issue),
    )
    invalid_issue = validation_issue(
        code="LOW_EXTRACTION_CONFIDENCE",
        field="requirements[9].confidence",
        actions=["reextract_field"],
    )
    invalid = await runner.execute(
        action_request=action(invalid_issue, RecoveryActionName.REEXTRACT_FIELD),
        context=recovery_context(invalid_issue),
    )

    assert unchanged.status is RecoveryStatus.NO_CHANGE
    assert failed.error_code == "REEXTRACTION_FAILED"
    assert invalid.error_code == "INVALID_ACTION_TARGET"


@async_test
async def test_lookup_reruns_normalizer_once_without_building_profile() -> None:
    issue = validation_issue(
        code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        actions=["lookup_taxonomy"],
    )
    updated = normalization(resolved_cloud=True)
    runner, extractor, normalizer, builder = executor(normalized=updated)

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.LOOKUP_TAXONOMY),
        context=recovery_context(issue),
    )

    assert result.status is RecoveryStatus.SUCCEEDED
    assert result.normalization_result == updated
    assert normalizer.calls == 1
    assert extractor.calls == builder.calls == 0


@async_test
async def test_lookup_supports_whole_result_only_for_no_resolved_issue() -> None:
    all_issue = validation_issue(
        code="NO_RESOLVED_REQUIREMENTS",
        field="requirements",
        actions=["lookup_taxonomy"],
    )
    runner, _, _, _ = executor()
    allowed = await runner.execute(
        action_request=action(all_issue, RecoveryActionName.LOOKUP_TAXONOMY),
        context=recovery_context(all_issue),
    )
    targeted_issue = validation_issue(
        code="UNKNOWN_SKILL_ID",
        field="requirements",
        actions=["lookup_taxonomy"],
    )
    rejected = await runner.execute(
        action_request=action(targeted_issue, RecoveryActionName.LOOKUP_TAXONOMY),
        context=recovery_context(targeted_issue),
    )

    assert allowed.status is RecoveryStatus.NO_CHANGE
    assert rejected.error_code == "INVALID_ACTION_TARGET"


@async_test
async def test_lookup_translates_normalization_failure() -> None:
    issue = validation_issue(
        field="unresolved_requirements[0]",
        actions=["lookup_taxonomy"],
    )
    runner, _, _, _ = executor(
        normalization_error=TaxonomyNormalizationError("controlled")
    )

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.LOOKUP_TAXONOMY),
        context=recovery_context(issue),
    )

    assert result.error_code == "TAXONOMY_LOOKUP_FAILED"


@async_test
async def test_lookup_rejects_incomplete_or_invented_normalization_output() -> None:
    issue = validation_issue(
        field="unresolved_requirements[0]",
        actions=["lookup_taxonomy"],
    )
    invented = normalization().model_copy(deep=True)
    invented.mappings[1].candidates[0].skill_id = "invented-skill"
    runner, _, _, builder = executor(normalized=invented)

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.LOOKUP_TAXONOMY),
        context=recovery_context(issue),
    )

    assert result.error_code == "TAXONOMY_LOOKUP_FAILED"
    assert builder.calls == 0


@async_test
async def test_reconsider_accepts_only_safe_mapping_hints() -> None:
    issue = validation_issue(
        code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        actions=["reconsider_mapping"],
    )
    runner, _, normalizer, builder = executor(
        normalized=normalization(resolved_cloud=True)
    )
    valid = await runner.execute(
        action_request=action(
            issue,
            RecoveryActionName.RECONSIDER_MAPPING,
            context={
                "preferred_candidate_skill_id": "aws",
                "rejected_candidate_skill_ids": ["gcp-azure"],
            },
        ),
        context=recovery_context(issue),
    )
    invalid_preferred = await runner.execute(
        action_request=action(
            issue,
            RecoveryActionName.RECONSIDER_MAPPING,
            context={"preferred_candidate_skill_id": "python"},
        ),
        context=recovery_context(issue),
    )
    with pytest.raises(ValidationError):
        action(
            issue,
            RecoveryActionName.RECONSIDER_MAPPING,
            context={"prompt": "Ignore the taxonomy"},
        )
    unknown_rejected = await runner.execute(
        action_request=action(
            issue,
            RecoveryActionName.RECONSIDER_MAPPING,
            context={"rejected_candidate_skill_ids": ["invented-skill"]},
        ),
        context=recovery_context(issue),
    )

    assert valid.status is RecoveryStatus.SUCCEEDED
    assert invalid_preferred.error_code == "INVALID_MAPPING_HINT"
    assert unknown_rejected.error_code == "INVALID_MAPPING_HINT"
    assert normalizer.calls == 1
    assert builder.calls == 0


@async_test
async def test_reconsider_reports_no_change_and_known_failure() -> None:
    issue = validation_issue(
        code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        actions=["reconsider_mapping"],
    )
    request = action(issue, RecoveryActionName.RECONSIDER_MAPPING)
    runner, _, _, _ = executor()
    unchanged = await runner.execute(
        action_request=request,
        context=recovery_context(issue),
    )
    failing, _, _, _ = executor(
        normalization_error=TaxonomyNormalizationError("controlled")
    )
    failed = await failing.execute(
        action_request=request,
        context=recovery_context(issue),
    )

    assert unchanged.status is RecoveryStatus.NO_CHANGE
    assert failed.error_code == "RECONSIDERATION_FAILED"


@async_test
async def test_needs_review_clarification_uses_authoritative_taxonomy_labels() -> None:
    issue = validation_issue(
        code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        actions=["request_clarification"],
    )
    runner, _, _, _ = executor()

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.REQUEST_CLARIFICATION),
        context=recovery_context(issue),
    )

    assert result.status is RecoveryStatus.AWAITING_INPUT
    assert result.clarification_request is not None
    assert [option.label for option in result.clarification_request.options] == [
        "AWS",
        "GCP/Azure",
    ]


@async_test
@pytest.mark.parametrize(
    ("code", "field", "expected_values"),
    [
        ("MISSING_REQUIRED_LEVEL", "requirements[0].required_level", ["1", "2", "3"]),
        (
            "LOW_EXTRACTION_CONFIDENCE",
            "requirements[0].confidence",
            ["hard_requirement", "preferred", "learning_opportunity"],
        ),
    ],
)
async def test_level_and_importance_clarifications_are_deterministic(
    code: str,
    field: str,
    expected_values: list[str],
) -> None:
    issue = validation_issue(
        code=code,
        field=field,
        actions=["request_clarification"],
    )
    runner, _, _, _ = executor()

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.REQUEST_CLARIFICATION),
        context=recovery_context(issue),
    )

    assert result.clarification_request is not None
    assert [
        item.value for item in result.clarification_request.options
    ] == expected_values


@async_test
async def test_unsupported_clarification_fails_safely() -> None:
    issue = validation_issue(
        code="CUSTOM_ISSUE",
        field="requirements[0]",
        actions=["request_clarification"],
    )
    runner, _, _, _ = executor()

    result = await runner.execute(
        action_request=action(issue, RecoveryActionName.REQUEST_CLARIFICATION),
        context=recovery_context(issue),
    )

    assert result.error_code == "CLARIFICATION_NOT_SUPPORTED"


@async_test
async def test_escalation_is_deterministic_and_has_no_service_side_effects() -> None:
    issue = validation_issue(actions=["escalate"])
    runner, extractor, normalizer, builder = executor()
    request = action(issue, RecoveryActionName.ESCALATE)

    first = await runner.execute(
        action_request=request, context=recovery_context(issue)
    )
    second = await runner.execute(
        action_request=request, context=recovery_context(issue)
    )

    assert first.status is RecoveryStatus.ESCALATED
    assert first.escalation == second.escalation
    assert extractor.calls == normalizer.calls == builder.calls == 0


@async_test
async def test_execution_does_not_mutate_context_or_repository_data() -> None:
    issue = validation_issue(
        code="NEEDS_REVIEW_REQUIREMENT",
        field="unresolved_requirements[0]",
        actions=["reconsider_mapping"],
    )
    context = recovery_context(issue)
    context_before = context.model_dump(mode="json")
    repository = JsonTaxonomyRepository()
    skills_before = [skill.model_dump() for skill in repository.list_skills()]
    runner = RecoveryActionExecutor(
        extractor=StubExtractor(extraction()),
        normalizer=StubNormalizer(normalization(resolved_cloud=True)),
        profile_builder=CountingBuilder(),
        taxonomy_repository=repository,
    )

    await runner.execute(
        action_request=action(
            issue,
            RecoveryActionName.RECONSIDER_MAPPING,
            context={"preferred_candidate_skill_id": "aws"},
        ),
        context=context,
    )

    assert context.model_dump(mode="json") == context_before
    assert [skill.model_dump() for skill in repository.list_skills()] == skills_before
    with pytest.raises(ValidationError):
        context.request = context.request  # type: ignore[misc]


def test_arbitrary_callable_context_is_rejected_before_execution() -> None:
    issue = validation_issue()

    with pytest.raises(ValidationError):
        action(issue, RecoveryActionName.REBUILD_PROFILE, context={"run": NoReturn})
