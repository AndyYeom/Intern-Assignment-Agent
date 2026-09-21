"""Hybrid deterministic and LLM-assisted taxonomy normalization."""

import re
from typing import Protocol

from project_catalog_agent.catalog.contracts import (
    ExactMatchSource,
    ExtractedRequirement,
    MappingStatus,
    MatchMethod,
    RequirementExtractionResult,
    TaxonomyCandidate,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
    TaxonomySelection,
    TaxonomySkill,
)
from project_catalog_agent.taxonomy.errors import (
    TaxonomyNormalizationError,
    TaxonomySelectionError,
    TaxonomySelectionResponseError,
)
from project_catalog_agent.taxonomy.repository import TaxonomyRepository
from project_catalog_agent.taxonomy.selector import TaxonomyMappingSelector

_TOKEN_PATTERN = re.compile(r"[a-z0-9+#.]+")


class TaxonomyNormalizer(Protocol):
    """Normalize extracted raw skills without changing extraction decisions."""

    async def normalize(
        self,
        extraction: RequirementExtractionResult,
    ) -> TaxonomyNormalizationResult:
        """Return one mapping for every input requirement."""
        ...


class HybridTaxonomyNormalizer:
    """Resolve exact values first, then use an optional conservative selector."""

    def __init__(
        self,
        repository: TaxonomyRepository,
        selector: TaxonomyMappingSelector | None = None,
    ) -> None:
        """Configure authoritative taxonomy lookup and optional selection."""
        self._repository = repository
        self._selector = selector

    async def normalize(
        self,
        extraction: RequirementExtractionResult,
    ) -> TaxonomyNormalizationResult:
        """Normalize skills in input order while retaining source indexes."""
        mappings: list[TaxonomyMapping] = []
        taxonomy_skills = tuple(
            skill for skill in self._repository.list_skills() if skill.active
        )

        for index, requirement in enumerate(extraction.requirements):
            exact_match = self._repository.resolve_exact(requirement.raw_skill)
            if exact_match is not None:
                method = (
                    MatchMethod.EXACT
                    if exact_match.match_source is ExactMatchSource.CANONICAL_NAME
                    else MatchMethod.ALIAS
                )
                basis = (
                    "Raw skill matched a canonical taxonomy name."
                    if method is MatchMethod.EXACT
                    else "Raw skill matched a taxonomy alias."
                )
                mappings.append(
                    TaxonomyMapping(
                        source_requirement_index=index,
                        raw_skill=requirement.raw_skill,
                        status=MappingStatus.RESOLVED,
                        match_method=method,
                        skill_id=exact_match.skill.skill_id,
                        canonical_skill=exact_match.skill.canonical_name,
                        decision_basis=basis,
                    )
                )
                continue

            if self._selector is None:
                mappings.append(
                    self._fallback_mapping(index, requirement, taxonomy_skills)
                )
                continue

            try:
                selection = await self._selector.select(
                    requirement=requirement,
                    taxonomy_skills=taxonomy_skills,
                )
            except TaxonomySelectionError:
                raise
            except Exception as error:
                msg = "taxonomy selector failed during normalization"
                raise TaxonomyNormalizationError(msg) from error
            mappings.append(self._mapping_from_selection(index, requirement, selection))

        unresolved_skills = [
            mapping.raw_skill
            for mapping in mappings
            if mapping.status in {MappingStatus.NEEDS_REVIEW, MappingStatus.UNMAPPED}
        ]
        return TaxonomyNormalizationResult(
            mappings=mappings,
            unresolved_skills=unresolved_skills,
        )

    def _mapping_from_selection(
        self,
        index: int,
        requirement: ExtractedRequirement,
        selection: TaxonomySelection,
    ) -> TaxonomyMapping:
        candidate_ids = list(dict.fromkeys(selection.candidate_skill_ids))
        candidates = [self._verified_candidate(skill_id) for skill_id in candidate_ids]

        if selection.decision == "select":
            selected_id = selection.selected_skill_id
            if selected_id is None:
                msg = "selector omitted selected skill ID"
                raise TaxonomySelectionResponseError(msg)
            selected_skill = self._verified_skill(selected_id)
            return TaxonomyMapping(
                source_requirement_index=index,
                raw_skill=requirement.raw_skill,
                status=MappingStatus.RESOLVED,
                match_method=MatchMethod.LLM_SELECTED,
                skill_id=selected_skill.skill_id,
                canonical_skill=selected_skill.canonical_name,
                candidates=candidates,
                match_score=selection.match_score,
                decision_basis=selection.decision_basis,
            )

        if selection.decision == "needs_review":
            if len(candidates) < 2:
                msg = "verified review candidates must contain two unique IDs"
                raise TaxonomySelectionResponseError(msg)
            return TaxonomyMapping(
                source_requirement_index=index,
                raw_skill=requirement.raw_skill,
                status=MappingStatus.NEEDS_REVIEW,
                match_method=MatchMethod.UNRESOLVED,
                candidates=candidates,
                match_score=selection.match_score,
                decision_basis=selection.decision_basis,
            )

        return TaxonomyMapping(
            source_requirement_index=index,
            raw_skill=requirement.raw_skill,
            status=MappingStatus.UNMAPPED,
            match_method=MatchMethod.UNRESOLVED,
            candidates=candidates,
            match_score=selection.match_score,
            decision_basis=selection.decision_basis,
        )

    def _verified_skill(self, skill_id: str) -> TaxonomySkill:
        skill = self._repository.get_by_id(skill_id)
        if skill is None or not skill.active:
            msg = f"taxonomy selector returned unknown skill ID {skill_id!r}"
            raise TaxonomySelectionResponseError(msg)
        return skill

    def _verified_candidate(self, skill_id: str) -> TaxonomyCandidate:
        skill = self._verified_skill(skill_id)
        return TaxonomyCandidate(
            skill_id=skill.skill_id,
            canonical_name=skill.canonical_name,
        )

    def _fallback_mapping(
        self,
        index: int,
        requirement: ExtractedRequirement,
        taxonomy_skills: tuple[TaxonomySkill, ...],
    ) -> TaxonomyMapping:
        candidates = self._lexical_candidates(requirement.raw_skill, taxonomy_skills)
        if len(candidates) >= 2:
            return TaxonomyMapping(
                source_requirement_index=index,
                raw_skill=requirement.raw_skill,
                status=MappingStatus.NEEDS_REVIEW,
                match_method=MatchMethod.UNRESOLVED,
                candidates=candidates,
                decision_basis=(
                    "Multiple taxonomy entries have plausible lexical overlap; "
                    "manual review is required because no selector is configured."
                ),
            )
        return TaxonomyMapping(
            source_requirement_index=index,
            raw_skill=requirement.raw_skill,
            status=MappingStatus.UNMAPPED,
            match_method=MatchMethod.UNRESOLVED,
            decision_basis=(
                "No deterministic match or unambiguous lexical candidates were "
                "available, and no selector is configured."
            ),
        )

    @staticmethod
    def _lexical_candidates(
        raw_skill: str,
        taxonomy_skills: tuple[TaxonomySkill, ...],
    ) -> list[TaxonomyCandidate]:
        raw_tokens = set(_TOKEN_PATTERN.findall(raw_skill.casefold()))
        matches: list[TaxonomyCandidate] = []
        for skill in taxonomy_skills:
            phrases = (skill.canonical_name, *skill.aliases)
            phrase_matches = any(
                bool(tokens := set(_TOKEN_PATTERN.findall(phrase.casefold())))
                and tokens <= raw_tokens
                for phrase in phrases
            )
            if phrase_matches:
                matches.append(
                    TaxonomyCandidate(
                        skill_id=skill.skill_id,
                        canonical_name=skill.canonical_name,
                    )
                )
        return matches
