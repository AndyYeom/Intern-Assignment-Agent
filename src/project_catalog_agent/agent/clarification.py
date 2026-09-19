"""Deterministic application of authorized clarification answers."""

import re

from pydantic import ValidationError

from project_catalog_agent.admin import AdminAuthorizer, AdminRole
from project_catalog_agent.agent.state import CatalogStateUpdater
from project_catalog_agent.catalog.contracts import (
    CatalogAgentState,
    CatalogStage,
    CatalogStatus,
    ClarificationApplicationResult,
    ClarificationApplicationStatus,
    ClarificationHistoryEntry,
    ClarificationRejectionCode,
    ClarificationResponse,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.errors import InvalidStateTransitionError
from project_catalog_agent.taxonomy import TaxonomyRepository

_LEVEL_PATH = re.compile(r"^requirements\[(\d+)]\.required_level$")
_IMPORTANCE_PATH = re.compile(r"^requirements\[(\d+)]\.(?:importance|confidence)$")
_EVIDENCE_PATH = re.compile(r"^requirements\[(\d+)]\.evidence_text$")
_PROVENANCE_EVIDENCE_PATH = re.compile(
    r"^requirements\[(\d+)]\.provenance\[(\d+)]\.evidence_text$"
)
_UNRESOLVED_PATH = re.compile(r"^unresolved_requirements\[(\d+)]$")


class ClarificationResponseProcessor:
    """Verify one answer and apply one deterministic artifact update."""

    def __init__(
        self,
        *,
        taxonomy_repository: TaxonomyRepository,
        state_updater: CatalogStateUpdater,
        admin_authorizer: AdminAuthorizer,
    ) -> None:
        self._taxonomy_repository = taxonomy_repository
        self._state_updater = state_updater
        self._admin_authorizer = admin_authorizer

    def apply(
        self,
        *,
        state: CatalogAgentState,
        response: ClarificationResponse,
    ) -> ClarificationApplicationResult:
        """Apply an authorized answer or return the first stable rejection."""
        if state.status is not CatalogStatus.AWAITING_CLARIFICATION:
            return self._reject(
                response, ClarificationRejectionCode.NO_PENDING_CLARIFICATION
            )
        pending = state.pending_clarification
        if pending is None:
            return self._reject(
                response, ClarificationRejectionCode.NO_PENDING_CLARIFICATION
            )
        if response.request_id != state.request.request_id:
            return self._reject(
                response, ClarificationRejectionCode.REQUEST_ID_MISMATCH
            )
        if pending.request_id != state.request.request_id:
            return self._reject(
                response, ClarificationRejectionCode.REQUEST_ID_MISMATCH
            )
        if response.clarification_id != pending.clarification_id:
            return self._reject(
                response, ClarificationRejectionCode.CLARIFICATION_ID_MISMATCH
            )
        if any(
            entry.clarification_id == response.clarification_id
            for entry in state.clarification_history
        ):
            return self._reject(
                response, ClarificationRejectionCode.CLARIFICATION_ALREADY_APPLIED
            )
        if not self._admin_authorizer.is_authorized(
            actor_id=response.answered_by,
            required_role=AdminRole.CLARIFIER,
        ):
            return self._reject(
                response, ClarificationRejectionCode.UNAUTHORIZED_RESPONDENT
            )
        try:
            response = ClarificationResponse.model_validate(response.model_dump())
        except ValidationError:
            return self._reject(
                response, ClarificationRejectionCode.INVALID_ANSWER_FORM
            )

        option = None
        if response.selected_value is not None:
            option = next(
                (
                    item
                    for item in pending.options
                    if item.value == response.selected_value
                ),
                None,
            )
            if option is None:
                return self._reject(
                    response, ClarificationRejectionCode.INVALID_SELECTED_OPTION
                )
            if option.skill_id is not None:
                skill = self._taxonomy_repository.get_by_id(option.skill_id)
                if skill is None or not skill.active:
                    return self._reject(
                        response, ClarificationRejectionCode.UNKNOWN_TAXONOMY_SKILL
                    )
        elif not pending.allow_free_text:
            return self._reject(
                response, ClarificationRejectionCode.FREE_TEXT_NOT_ALLOWED
            )

        try:
            updated: RequirementExtractionResult | TaxonomyNormalizationResult
            if pending.issue_code in {
                "NEEDS_REVIEW_REQUIREMENT",
                "UNMAPPED_REQUIREMENT",
            }:
                if option is None or option.skill_id is None:
                    return self._reject(
                        response, ClarificationRejectionCode.UNSUPPORTED_CLARIFICATION
                    )
                updated = self._apply_taxonomy_selection(
                    state, pending.field, option.skill_id
                )
                stage = CatalogStage.NORMALIZED
            elif pending.issue_code == "MISSING_REQUIRED_LEVEL":
                if response.selected_value is None:
                    return self._reject(
                        response, ClarificationRejectionCode.INVALID_ANSWER_FORM
                    )
                try:
                    level = ProficiencyLevel(int(response.selected_value))
                except (TypeError, ValueError):
                    return self._reject(
                        response, ClarificationRejectionCode.INVALID_SELECTED_OPTION
                    )
                updated = self._apply_level(state, pending.field, level)
                stage = CatalogStage.EXTRACTED
            elif pending.issue_code == "LOW_EXTRACTION_CONFIDENCE":
                if response.selected_value is None:
                    return self._reject(
                        response, ClarificationRejectionCode.INVALID_ANSWER_FORM
                    )
                updated = self._apply_importance(
                    state, pending.field, response.selected_value
                )
                stage = CatalogStage.EXTRACTED
            elif pending.issue_code in {
                "EVIDENCE_NOT_VERBATIM",
                "PROVENANCE_EVIDENCE_NOT_VERBATIM",
            }:
                if response.free_text is None:
                    return self._reject(
                        response, ClarificationRejectionCode.INVALID_ANSWER_FORM
                    )
                if response.free_text not in state.request.project_description:
                    return self._reject(
                        response, ClarificationRejectionCode.EVIDENCE_NOT_VERBATIM
                    )
                updated = self._apply_evidence(state, pending.field, response.free_text)
                stage = CatalogStage.EXTRACTED
            else:
                return self._reject(
                    response, ClarificationRejectionCode.UNSUPPORTED_CLARIFICATION
                )
        except _ApplicationRejection as rejection:
            return self._reject(response, rejection.code)

        history = ClarificationHistoryEntry(
            sequence=len(state.clarification_history) + 1,
            clarification_id=response.clarification_id,
            issue_code=pending.issue_code,
            field=pending.field,
            answered_by=response.answered_by,
            answer_type="selected_value"
            if response.selected_value is not None
            else "free_text",
            accepted_value=response.selected_value or response.free_text or "",
            submitted_at=response.submitted_at,
            applied_stage=stage,
        )
        try:
            new_state = self._state_updater.apply_clarification_update(
                state,
                history_entry=history,
                updated_extraction=updated
                if isinstance(updated, RequirementExtractionResult)
                else None,
                updated_normalization=updated
                if isinstance(updated, TaxonomyNormalizationResult)
                else None,
            )
        except (InvalidStateTransitionError, ValidationError):
            return self._reject(
                response, ClarificationRejectionCode.ANSWER_APPLICATION_FAILED
            )
        return ClarificationApplicationResult(
            request_id=response.request_id,
            clarification_id=response.clarification_id,
            status=ClarificationApplicationStatus.APPLIED,
            changed=True,
            updated_state=new_state,
            message="The verified admin clarification was applied.",
        )

    def _apply_taxonomy_selection(
        self, state: CatalogAgentState, field: str, skill_id: str
    ) -> TaxonomyNormalizationResult:
        match = _UNRESOLVED_PATH.fullmatch(field)
        if match is None:
            raise _ApplicationRejection(ClarificationRejectionCode.INVALID_TARGET_FIELD)
        unresolved_index = int(match.group(1))
        profile = state.candidate_profile
        normalization = state.normalization_result
        if (
            profile is None
            or normalization is None
            or unresolved_index >= len(profile.unresolved_requirements)
        ):
            raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
        source_index = profile.unresolved_requirements[
            unresolved_index
        ].source_requirement_index
        skill = self._taxonomy_repository.get_by_id(skill_id)
        if skill is None or not skill.active:
            raise _ApplicationRejection(
                ClarificationRejectionCode.UNKNOWN_TAXONOMY_SKILL
            )
        mappings = [item.model_copy(deep=True) for item in normalization.mappings]
        mapping_position = next(
            (
                i
                for i, item in enumerate(mappings)
                if item.source_requirement_index == source_index
            ),
            None,
        )
        if mapping_position is None:
            raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
        old = mappings[mapping_position]
        mappings[mapping_position] = TaxonomyMapping(
            source_requirement_index=old.source_requirement_index,
            raw_skill=old.raw_skill,
            status=MappingStatus.RESOLVED,
            match_method=MatchMethod.CLARIFIED,
            skill_id=skill.skill_id,
            canonical_skill=skill.canonical_name,
            candidates=[],
            decision_basis="Resolved from verified admin clarification.",
        )
        unresolved = [
            item.raw_skill
            for item in mappings
            if item.status is not MappingStatus.RESOLVED
        ]
        return TaxonomyNormalizationResult(
            mappings=mappings, unresolved_skills=list(dict.fromkeys(unresolved))
        )

    def _source_indexes(
        self, state: CatalogAgentState, requirement_index: int
    ) -> list[int]:
        profile = state.candidate_profile
        extraction = state.extraction_result
        if (
            profile is None
            or extraction is None
            or requirement_index >= len(profile.requirements)
        ):
            raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
        indexes = list(
            dict.fromkeys(
                item.source_requirement_index
                for item in profile.requirements[requirement_index].provenance
            )
        )
        if not indexes or any(
            index >= len(extraction.requirements) for index in indexes
        ):
            raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
        return indexes

    def _apply_level(
        self, state: CatalogAgentState, field: str, level: ProficiencyLevel
    ) -> RequirementExtractionResult:
        match = _LEVEL_PATH.fullmatch(field)
        if match is None:
            raise _ApplicationRejection(ClarificationRejectionCode.INVALID_TARGET_FIELD)
        return self._update_extraction(
            state,
            self._source_indexes(state, int(match.group(1))),
            "required_level",
            level,
        )

    def _apply_importance(
        self, state: CatalogAgentState, field: str, value: str
    ) -> RequirementExtractionResult:
        match = _IMPORTANCE_PATH.fullmatch(field)
        if match is None:
            raise _ApplicationRejection(ClarificationRejectionCode.INVALID_TARGET_FIELD)
        indexes = self._source_indexes(state, int(match.group(1)))
        aliases = {
            "required": RequirementImportance.HARD_REQUIREMENT,
            "hard_requirement": RequirementImportance.HARD_REQUIREMENT,
            "preferred": RequirementImportance.PREFERRED,
            "learning_opportunity": RequirementImportance.LEARNING_OPPORTUNITY,
        }
        if value == "not_a_requirement":
            extraction = state.extraction_result
            if extraction is None:
                raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
            requirements = [
                item.model_copy(deep=True)
                for i, item in enumerate(extraction.requirements)
                if i not in set(indexes)
            ]
            return RequirementExtractionResult.model_validate(
                {**extraction.model_dump(), "requirements": requirements}
            )
        importance = aliases.get(value)
        if importance is None:
            raise _ApplicationRejection(
                ClarificationRejectionCode.INVALID_SELECTED_OPTION
            )
        return self._update_extraction(state, indexes, "importance", importance)

    def _apply_evidence(
        self, state: CatalogAgentState, field: str, evidence: str
    ) -> RequirementExtractionResult:
        provenance = _PROVENANCE_EVIDENCE_PATH.fullmatch(field)
        if provenance is not None:
            requirement_index, provenance_index = map(int, provenance.groups())
            profile = state.candidate_profile
            if (
                profile is None
                or requirement_index >= len(profile.requirements)
                or provenance_index
                >= len(profile.requirements[requirement_index].provenance)
            ):
                raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
            indexes = [
                profile.requirements[requirement_index]
                .provenance[provenance_index]
                .source_requirement_index
            ]
        else:
            match = _EVIDENCE_PATH.fullmatch(field)
            if match is None:
                raise _ApplicationRejection(
                    ClarificationRejectionCode.INVALID_TARGET_FIELD
                )
            indexes = self._source_indexes(state, int(match.group(1)))
            if len(indexes) != 1:
                raise _ApplicationRejection(
                    ClarificationRejectionCode.UNSUPPORTED_CLARIFICATION
                )
        return self._update_extraction(state, indexes, "evidence_text", evidence)

    @staticmethod
    def _update_extraction(
        state: CatalogAgentState, indexes: list[int], field: str, value: object
    ) -> RequirementExtractionResult:
        extraction = state.extraction_result
        if extraction is None:
            raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
        requirements = [item.model_copy(deep=True) for item in extraction.requirements]
        if any(index >= len(requirements) for index in indexes):
            raise _ApplicationRejection(ClarificationRejectionCode.TARGET_NOT_FOUND)
        for index in indexes:
            requirements[index] = requirements[index].model_copy(update={field: value})
        return RequirementExtractionResult.model_validate(
            {**extraction.model_dump(), "requirements": requirements}
        )

    @staticmethod
    def _reject(
        response: ClarificationResponse, code: ClarificationRejectionCode
    ) -> ClarificationApplicationResult:
        return ClarificationApplicationResult(
            request_id=response.request_id,
            clarification_id=response.clarification_id,
            status=ClarificationApplicationStatus.REJECTED,
            changed=False,
            message="The clarification response was rejected.",
            error_code=code.value,
        )


class _ApplicationRejection(Exception):
    def __init__(self, code: ClarificationRejectionCode) -> None:
        super().__init__(code.value)
        self.code = code
