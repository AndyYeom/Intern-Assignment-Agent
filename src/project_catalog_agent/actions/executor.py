"""Fixed-dispatch executor for explicit bounded recovery actions."""

from collections.abc import Awaitable, Callable

from project_catalog_agent.catalog.contracts import (
    ClarificationOption,
    ClarificationRequest,
    EscalationRequest,
    MappingStatus,
    ProficiencyLevel,
    ProjectRequirement,
    RecoveryActionName,
    RecoveryActionRequest,
    RecoveryActionResult,
    RecoveryContext,
    RecoveryStatus,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyNormalizationResult,
    UnresolvedProjectRequirement,
    ValidationIssue,
)
from project_catalog_agent.errors import (
    ProjectProfileBuildError,
    RequirementExtractionError,
)
from project_catalog_agent.extraction import RequirementExtractor
from project_catalog_agent.profile import ProjectProfileBuilder
from project_catalog_agent.taxonomy import (
    TaxonomyNormalizationError,
    TaxonomyNormalizer,
    TaxonomyRepository,
)

ActionHandler = Callable[
    [RecoveryActionRequest, RecoveryContext, ValidationIssue],
    Awaitable[RecoveryActionResult],
]


class _InvalidActionTargetError(Exception):
    """Internal signal for a missing or out-of-range explicit target."""


class RecoveryActionExecutor:
    """Execute one explicitly requested action through fixed bounded handlers."""

    def __init__(
        self,
        *,
        extractor: RequirementExtractor,
        normalizer: TaxonomyNormalizer,
        profile_builder: ProjectProfileBuilder,
        taxonomy_repository: TaxonomyRepository,
    ) -> None:
        """Configure existing services without performing any action."""
        self._extractor = extractor
        self._normalizer = normalizer
        self._profile_builder = profile_builder
        self._taxonomy_repository = taxonomy_repository
        self._handlers: dict[RecoveryActionName, ActionHandler] = {
            RecoveryActionName.REBUILD_PROFILE: self._rebuild_profile,
            RecoveryActionName.REEXTRACT_FIELD: self._reextract_field,
            RecoveryActionName.LOOKUP_TAXONOMY: self._lookup_taxonomy,
            RecoveryActionName.RECONSIDER_MAPPING: self._reconsider_mapping,
            RecoveryActionName.REQUEST_CLARIFICATION: self._request_clarification,
            RecoveryActionName.ESCALATE: self._escalate,
        }

    async def execute(
        self,
        *,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
    ) -> RecoveryActionResult:
        """Guard permission and dispatch exactly one registered action."""
        if action_request.request_id != context.request.request_id:
            return self._failed(
                action_request,
                "INVALID_ACTION_TARGET",
                "Recovery request does not match the current project request.",
            )
        issue = next(
            (
                candidate
                for candidate in context.validation_result.issues
                if candidate.code == action_request.issue_code
                and candidate.field == action_request.issue_field
            ),
            None,
        )
        if issue is None:
            return self._failed(
                action_request,
                "ISSUE_NOT_FOUND",
                "The referenced validation issue is not present.",
            )
        if action_request.action.value not in issue.resolvable_by:
            return self._failed(
                action_request,
                "ACTION_NOT_PERMITTED",
                "The requested action is not permitted for this issue.",
            )
        return await self._handlers[action_request.action](
            action_request,
            context,
            issue,
        )

    async def _rebuild_profile(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        _: ValidationIssue,
    ) -> RecoveryActionResult:
        try:
            profile = self._profile_builder.build(
                request=context.request.model_copy(deep=True),
                extraction=context.extraction_result.model_copy(deep=True),
                normalization=context.normalization_result.model_copy(deep=True),
            )
        except ProjectProfileBuildError:
            return self._failed(
                action_request,
                "PROFILE_REBUILD_FAILED",
                "The profile could not be rebuilt from current artifacts.",
            )
        if profile == context.candidate_profile:
            return self._no_change(
                action_request,
                "Profile rebuilding produced no change.",
            )
        return RecoveryActionResult(
            request_id=action_request.request_id,
            action=action_request.action,
            issue_code=action_request.issue_code,
            status=RecoveryStatus.SUCCEEDED,
            changed=True,
            candidate_profile=profile,
            message="Profile rebuilt from current extraction and normalization.",
        )

    async def _reextract_field(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        _: ValidationIssue,
    ) -> RecoveryActionResult:
        try:
            self._target_source_index(action_request, context, allow_all=True)
        except _InvalidActionTargetError:
            return self._failed(
                action_request,
                "INVALID_ACTION_TARGET",
                "The requirement target for re-extraction is invalid.",
            )
        try:
            extracted = await self._extractor.extract(
                context.request.model_copy(deep=True)
            )
            extracted = RequirementExtractionResult.model_validate(
                extracted.model_dump()
            )
        except RequirementExtractionError:
            return self._failed(
                action_request,
                "REEXTRACTION_FAILED",
                "Requirement extraction could not be completed.",
            )
        if extracted == context.extraction_result:
            return self._no_change(
                action_request,
                "Requirement extraction produced no change.",
            )
        return RecoveryActionResult(
            request_id=action_request.request_id,
            action=action_request.action,
            issue_code=action_request.issue_code,
            status=RecoveryStatus.SUCCEEDED,
            changed=True,
            extraction_result=extracted,
            message="Requirement extraction produced an updated result.",
        )

    async def _lookup_taxonomy(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        issue: ValidationIssue,
    ) -> RecoveryActionResult:
        try:
            self._target_source_index(
                action_request,
                context,
                allow_all=issue.code == "NO_RESOLVED_REQUIREMENTS",
            )
        except _InvalidActionTargetError:
            return self._failed(
                action_request,
                "INVALID_ACTION_TARGET",
                "A valid requirement target is required for taxonomy lookup.",
            )
        return await self._rerun_normalization(
            action_request,
            context,
            failure_code="TAXONOMY_LOOKUP_FAILED",
            failure_message="Taxonomy lookup could not be completed.",
            unchanged_message="Taxonomy lookup produced no change.",
            changed_message="Taxonomy lookup produced updated normalization.",
        )

    async def _reconsider_mapping(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        _: ValidationIssue,
    ) -> RecoveryActionResult:
        try:
            source_index = self._target_source_index(
                action_request,
                context,
                allow_all=False,
            )
        except _InvalidActionTargetError:
            return self._failed(
                action_request,
                "INVALID_ACTION_TARGET",
                "A valid requirement target is required for reconsideration.",
            )
        if source_index is None or not self._valid_mapping_hints(
            action_request,
            context,
            source_index,
        ):
            return self._failed(
                action_request,
                "INVALID_MAPPING_HINT",
                "Mapping hints are invalid or unsafe.",
            )
        return await self._rerun_normalization(
            action_request,
            context,
            failure_code="RECONSIDERATION_FAILED",
            failure_message="Mapping reconsideration could not be completed.",
            unchanged_message="Mapping reconsideration produced no change.",
            changed_message="Mapping reconsideration updated normalization.",
        )

    async def _request_clarification(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        _: ValidationIssue,
    ) -> RecoveryActionResult:
        try:
            clarification = self._build_clarification(action_request, context)
        except _InvalidActionTargetError:
            return self._failed(
                action_request,
                "INVALID_ACTION_TARGET",
                "A valid issue target is required for clarification.",
            )
        if clarification is None:
            return self._failed(
                action_request,
                "CLARIFICATION_NOT_SUPPORTED",
                "This issue cannot be converted into a safe clarification.",
            )
        return RecoveryActionResult(
            request_id=action_request.request_id,
            action=action_request.action,
            issue_code=action_request.issue_code,
            status=RecoveryStatus.AWAITING_INPUT,
            changed=False,
            clarification_request=clarification,
            message="A clarification request was prepared for later delivery.",
        )

    async def _escalate(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        _: ValidationIssue,
    ) -> RecoveryActionResult:
        escalation = EscalationRequest(
            escalation_id=self._stable_id("escalation", action_request),
            request_id=action_request.request_id,
            issue_code=action_request.issue_code,
            field=action_request.issue_field,
            reason="Automatic recovery is unsafe or has been exhausted.",
            context_summary=(
                f"Request {action_request.request_id!r} is blocked by issue "
                f"{action_request.issue_code!r} at {action_request.issue_field!r}."
            ),
            recommended_review=(
                "Review the affected field, its source evidence, and taxonomy "
                "mapping before resuming processing."
            ),
        )
        return RecoveryActionResult(
            request_id=action_request.request_id,
            action=action_request.action,
            issue_code=action_request.issue_code,
            status=RecoveryStatus.ESCALATED,
            changed=False,
            escalation=escalation,
            message="A human-review escalation was prepared for later delivery.",
        )

    async def _rerun_normalization(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        *,
        failure_code: str,
        failure_message: str,
        unchanged_message: str,
        changed_message: str,
    ) -> RecoveryActionResult:
        try:
            normalized = await self._normalizer.normalize(
                context.extraction_result.model_copy(deep=True)
            )
            normalized = TaxonomyNormalizationResult.model_validate(
                normalized.model_dump()
            )
        except TaxonomyNormalizationError:
            return self._failed(action_request, failure_code, failure_message)
        if not self._normalization_is_safe_and_complete(normalized, context):
            return self._failed(action_request, failure_code, failure_message)
        if normalized == context.normalization_result:
            return self._no_change(action_request, unchanged_message)
        return RecoveryActionResult(
            request_id=action_request.request_id,
            action=action_request.action,
            issue_code=action_request.issue_code,
            status=RecoveryStatus.SUCCEEDED,
            changed=True,
            normalization_result=normalized,
            message=changed_message,
        )

    def _normalization_is_safe_and_complete(
        self,
        normalization: TaxonomyNormalizationResult,
        context: RecoveryContext,
    ) -> bool:
        requirements = context.extraction_result.requirements
        if len(normalization.mappings) != len(requirements):
            return False
        seen_indexes: set[int] = set()
        expected_unresolved: list[str] = []
        for mapping in normalization.mappings:
            index = mapping.source_requirement_index
            if (
                index in seen_indexes
                or index >= len(requirements)
                or mapping.raw_skill != requirements[index].raw_skill
            ):
                return False
            seen_indexes.add(index)
            if mapping.skill_id is not None:
                skill = self._taxonomy_repository.get_by_id(mapping.skill_id)
                if skill is None or skill.canonical_name != mapping.canonical_skill:
                    return False
            if any(
                self._taxonomy_repository.get_by_id(candidate.skill_id) is None
                for candidate in mapping.candidates
            ):
                return False
            if mapping.status is not MappingStatus.RESOLVED:
                expected_unresolved.append(mapping.raw_skill)
        return (
            seen_indexes == set(range(len(requirements)))
            and normalization.unresolved_skills == expected_unresolved
        )

    def _target_source_index(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        *,
        allow_all: bool,
    ) -> int | None:
        source_index: int | None = None
        unresolved_index = action_request.target_unresolved_index
        requirement_index = action_request.target_requirement_index
        if unresolved_index is not None:
            if unresolved_index >= len(
                context.candidate_profile.unresolved_requirements
            ):
                raise _InvalidActionTargetError
            source_index = context.candidate_profile.unresolved_requirements[
                unresolved_index
            ].source_requirement_index
        elif requirement_index is not None:
            if requirement_index >= len(context.candidate_profile.requirements):
                raise _InvalidActionTargetError
            provenance = context.candidate_profile.requirements[
                requirement_index
            ].provenance
            provenance_index = action_request.target_provenance_index or 0
            if provenance_index >= len(provenance):
                raise _InvalidActionTargetError
            source_index = provenance[provenance_index].source_requirement_index
        elif not allow_all:
            raise _InvalidActionTargetError

        if source_index is not None and source_index >= len(
            context.extraction_result.requirements
        ):
            raise _InvalidActionTargetError
        return source_index

    def _valid_mapping_hints(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
        source_index: int,
    ) -> bool:
        allowed_keys = {
            "preferred_candidate_skill_id",
            "rejected_candidate_skill_ids",
        }
        if set(action_request.context) - allowed_keys:
            return False
        mapping = next(
            (
                item
                for item in context.normalization_result.mappings
                if item.source_requirement_index == source_index
            ),
            None,
        )
        if mapping is None:
            return False
        candidate_ids = {candidate.skill_id for candidate in mapping.candidates}
        preferred = action_request.context.get("preferred_candidate_skill_id")
        if preferred is not None and (
            not isinstance(preferred, str) or preferred not in candidate_ids
        ):
            return False
        rejected = action_request.context.get("rejected_candidate_skill_ids", [])
        return not (
            not isinstance(rejected, list)
            or any(
                not isinstance(item, str)
                or self._taxonomy_repository.get_by_id(item) is None
                for item in rejected
            )
        )

    def _build_clarification(
        self,
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
    ) -> ClarificationRequest | None:
        options: list[ClarificationOption]
        raw_skill: str | None = None
        allow_free_text = True
        if action_request.issue_code == "NEEDS_REVIEW_REQUIREMENT":
            unresolved = self._target_unresolved(action_request, context)
            raw_skill = unresolved.raw_skill
            options = []
            for candidate_id in unresolved.candidate_skill_ids:
                skill = self._taxonomy_repository.get_by_id(candidate_id)
                if skill is None:
                    return None
                options.append(
                    ClarificationOption(
                        value=candidate_id,
                        label=skill.canonical_name,
                        skill_id=candidate_id,
                    )
                )
            if len(options) < 2:
                return None
            question = (
                f"Which taxonomy skill best represents {raw_skill!r} for this project?"
            )
        elif action_request.issue_code == "MISSING_REQUIRED_LEVEL":
            requirement = self._target_requirement(action_request, context)
            raw_skill = requirement.canonical_name
            options = [
                ClarificationOption(
                    value=str(int(level)),
                    label=f"{level.name.title()} ({int(level)})",
                )
                for level in ProficiencyLevel
            ]
            question = f"What minimum proficiency level is required for {raw_skill}?"
        elif action_request.issue_code == "LOW_EXTRACTION_CONFIDENCE":
            requirement = self._target_requirement(action_request, context)
            raw_skill = requirement.canonical_name
            options = [
                ClarificationOption(
                    value=importance.value,
                    label=importance.value.replace("_", " ").title(),
                )
                for importance in RequirementImportance
            ]
            question = (
                f"Is {raw_skill} a required, preferred, or learning-opportunity "
                "skill for this project?"
            )
        elif action_request.issue_code == "PROVENANCE_EVIDENCE_NOT_VERBATIM":
            requirement = self._target_requirement(action_request, context)
            raw_skill = requirement.canonical_name
            options = []
            allow_free_text = True
            question = (
                f"What exact project-description text supports {raw_skill} at "
                f"{action_request.issue_field}?"
            )
        else:
            return None
        return ClarificationRequest(
            clarification_id=self._stable_id("clarification", action_request),
            request_id=action_request.request_id,
            issue_code=action_request.issue_code,
            field=action_request.issue_field,
            question=question,
            related_raw_skill=raw_skill,
            options=options,
            allow_free_text=allow_free_text,
        )

    @staticmethod
    def _target_requirement(
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
    ) -> ProjectRequirement:
        index = action_request.target_requirement_index
        if index is None or index >= len(context.candidate_profile.requirements):
            raise _InvalidActionTargetError
        return context.candidate_profile.requirements[index]

    @staticmethod
    def _target_unresolved(
        action_request: RecoveryActionRequest,
        context: RecoveryContext,
    ) -> UnresolvedProjectRequirement:
        index = action_request.target_unresolved_index
        if index is None or index >= len(
            context.candidate_profile.unresolved_requirements
        ):
            raise _InvalidActionTargetError
        return context.candidate_profile.unresolved_requirements[index]

    @staticmethod
    def _stable_id(prefix: str, action_request: RecoveryActionRequest) -> str:
        field = "".join(
            character if character.isalnum() else "-"
            for character in action_request.issue_field
        ).strip("-")
        return (
            f"{prefix}-{action_request.request_id}-{action_request.issue_code}-{field}"
        )

    @staticmethod
    def _failed(
        action_request: RecoveryActionRequest,
        error_code: str,
        message: str,
    ) -> RecoveryActionResult:
        return RecoveryActionResult(
            request_id=action_request.request_id,
            action=action_request.action,
            issue_code=action_request.issue_code,
            status=RecoveryStatus.FAILED,
            changed=False,
            message=message,
            error_code=error_code,
        )

    @staticmethod
    def _no_change(
        action_request: RecoveryActionRequest,
        message: str,
    ) -> RecoveryActionResult:
        return RecoveryActionResult(
            request_id=action_request.request_id,
            action=action_request.action,
            issue_code=action_request.issue_code,
            status=RecoveryStatus.NO_CHANGE,
            changed=False,
            message=message,
        )
