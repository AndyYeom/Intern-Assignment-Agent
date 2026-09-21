"""Deterministic construction of candidate project profiles."""

from dataclasses import dataclass

from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    MappingStatus,
    ProjectProfile,
    ProjectRequirement,
    RequirementExtractionResult,
    RequirementProvenance,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
    UnresolvedProjectRequirement,
)
from project_catalog_agent.errors import ProjectProfileBuildError
from project_catalog_agent.profile.merge import (
    dominance_key,
    maximum_required_level,
    strongest_importance,
)


@dataclass(frozen=True, slots=True)
class _Contribution:
    """One validated extraction-to-taxonomy join."""

    index: int
    requirement: ExtractedRequirement
    mapping: TaxonomyMapping


class ProjectProfileBuilder:
    """Build a candidate profile without I/O, taxonomy lookup, or LLM calls."""

    def build(
        self,
        *,
        request: CreateProjectRequest,
        extraction: RequirementExtractionResult,
        normalization: TaxonomyNormalizationResult,
    ) -> ProjectProfile:
        """Validate, join, merge, and return one candidate project profile."""
        mappings_by_index = self._validate_and_index(extraction, normalization)
        resolved: dict[str, list[_Contribution]] = {}
        unresolved: list[UnresolvedProjectRequirement] = []

        for index, requirement in enumerate(extraction.requirements):
            mapping = mappings_by_index[index]
            if mapping.status is MappingStatus.RESOLVED:
                skill_id = mapping.skill_id
                if skill_id is None:
                    msg = f"resolved mapping at source index {index} has no skill ID"
                    raise ProjectProfileBuildError(msg)
                resolved.setdefault(skill_id, []).append(
                    _Contribution(index, requirement, mapping)
                )
            else:
                unresolved.append(
                    UnresolvedProjectRequirement(
                        source_requirement_index=index,
                        raw_skill=requirement.raw_skill,
                        mapping_status=mapping.status,
                        importance=requirement.importance,
                        required_level=requirement.required_level,
                        evidence_text=requirement.evidence_text,
                        candidate_skill_ids=[
                            candidate.skill_id for candidate in mapping.candidates
                        ],
                    )
                )

        ordered_groups = sorted(
            resolved.values(),
            key=lambda contributions: min(item.index for item in contributions),
        )
        requirements = [self._merge_group(group) for group in ordered_groups]
        unresolved_skills = list(dict.fromkeys(item.raw_skill for item in unresolved))

        try:
            return ProjectProfile(
                request_id=request.request_id,
                project_name=request.project_name,
                project_description=request.project_description,
                project_summary=extraction.project_summary,
                requirements=requirements,
                unresolved_skills=unresolved_skills,
                unresolved_requirements=unresolved,
            )
        except ValidationError as error:
            msg = "profile output could not be validated"
            raise ProjectProfileBuildError(msg) from error

    @staticmethod
    def _validate_and_index(
        extraction: RequirementExtractionResult,
        normalization: TaxonomyNormalizationResult,
    ) -> dict[int, TaxonomyMapping]:
        requirement_count = len(extraction.requirements)
        indexed: dict[int, TaxonomyMapping] = {}

        for mapping in normalization.mappings:
            index = mapping.source_requirement_index
            if index < 0 or index >= requirement_count:
                msg = f"mapping source index {index} is out of range"
                raise ProjectProfileBuildError(msg)
            if index in indexed:
                msg = f"duplicate normalization mapping for source index {index}"
                raise ProjectProfileBuildError(msg)

            requirement = extraction.requirements[index]
            if mapping.raw_skill != requirement.raw_skill:
                msg = f"raw skill mismatch at source index {index}"
                raise ProjectProfileBuildError(msg)
            ProjectProfileBuilder._validate_mapping_structure(mapping, index)
            indexed[index] = mapping

        missing_indexes = sorted(set(range(requirement_count)) - set(indexed))
        if missing_indexes:
            msg = (
                "Missing normalization mapping for source requirement index "
                f"{missing_indexes[0]}."
            )
            raise ProjectProfileBuildError(msg)
        return indexed

    @staticmethod
    def _validate_mapping_structure(mapping: TaxonomyMapping, index: int) -> None:
        if mapping.status not in {
            MappingStatus.RESOLVED,
            MappingStatus.NEEDS_REVIEW,
            MappingStatus.UNMAPPED,
        }:
            msg = f"mapping at source index {index} has an invalid status"
            raise ProjectProfileBuildError(msg)
        has_skill_id = mapping.skill_id is not None
        has_canonical_skill = mapping.canonical_skill is not None
        if mapping.status is MappingStatus.RESOLVED:
            if not (has_skill_id and has_canonical_skill):
                msg = f"resolved mapping at source index {index} is incomplete"
                raise ProjectProfileBuildError(msg)
        elif has_skill_id or has_canonical_skill:
            msg = f"unresolved mapping at source index {index} claims a skill"
            raise ProjectProfileBuildError(msg)

    @staticmethod
    def _merge_group(contributions: list[_Contribution]) -> ProjectRequirement:
        ordered = sorted(contributions, key=lambda item: item.index)
        first_mapping = ordered[0].mapping
        skill_id = first_mapping.skill_id
        canonical_name = first_mapping.canonical_skill
        if skill_id is None or canonical_name is None:
            msg = f"resolved mapping at source index {ordered[0].index} is incomplete"
            raise ProjectProfileBuildError(msg)

        for contribution in ordered[1:]:
            if contribution.mapping.canonical_skill != canonical_name:
                msg = (
                    f"canonical name mismatch for skill ID {skill_id!r} at source "
                    f"index {contribution.index}"
                )
                raise ProjectProfileBuildError(msg)

        importance = strongest_importance(
            item.requirement.importance for item in ordered
        )
        required_level = maximum_required_level(
            item.requirement.required_level for item in ordered
        )
        dominant = max(
            ordered,
            key=lambda item: dominance_key(
                importance=item.requirement.importance,
                required_level=item.requirement.required_level,
                confidence=item.requirement.confidence,
                source_requirement_index=item.index,
            ),
        )
        provenance = [
            RequirementProvenance(
                source_requirement_index=item.index,
                raw_skill=item.requirement.raw_skill,
                importance=item.requirement.importance,
                required_level=item.requirement.required_level,
                evidence_text=item.requirement.evidence_text,
                extraction_decision_basis=item.requirement.decision_basis,
                extraction_confidence=item.requirement.confidence,
                match_method=item.mapping.match_method,
                taxonomy_decision_basis=item.mapping.decision_basis,
            )
            for item in ordered
        ]
        decision_basis = (
            dominant.requirement.decision_basis
            if len(ordered) == 1
            else (
                f"Merged from {len(ordered)} extracted requirements mapped to "
                f"canonical skill '{skill_id}'."
            )
        )
        return ProjectRequirement(
            skill_id=skill_id,
            canonical_name=canonical_name,
            importance=importance,
            required_level=required_level,
            evidence_text=dominant.requirement.evidence_text,
            confidence=dominant.requirement.confidence,
            decision_basis=decision_basis,
            provenance=provenance,
        )


def build_project_profile(
    *,
    request: CreateProjectRequest,
    extraction: RequirementExtractionResult,
    normalization: TaxonomyNormalizationResult,
) -> ProjectProfile:
    """Build a candidate profile through the default deterministic builder."""
    return ProjectProfileBuilder().build(
        request=request,
        extraction=extraction,
        normalization=normalization,
    )
