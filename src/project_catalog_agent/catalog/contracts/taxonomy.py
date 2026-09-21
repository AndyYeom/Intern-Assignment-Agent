"""Skill taxonomy contracts."""

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from project_catalog_agent.catalog.contracts.common import (
    ContractModel,
    MappingStatus,
    MatchMethod,
)

SkillId = Annotated[str, Field(min_length=1, max_length=100)]
SkillName = Annotated[str, Field(min_length=1, max_length=200)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class TaxonomySkill(ContractModel):
    """A skill defined in the catalog taxonomy."""

    skill_id: SkillId
    canonical_name: SkillName
    aliases: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    category: Annotated[str, Field(min_length=1, max_length=200)]
    active: bool = True


class TaxonomyCandidate(ContractModel):
    """A possible taxonomy match for a raw skill."""

    skill_id: SkillId
    canonical_name: SkillName
    score: Confidence | None = None


class TaxonomyMapping(ContractModel):
    """Mapping between an extracted skill and the taxonomy."""

    source_requirement_index: Annotated[int, Field(ge=0)]
    raw_skill: Annotated[str, Field(min_length=1)]
    status: MappingStatus
    match_method: MatchMethod
    skill_id: SkillId | None = None
    canonical_skill: SkillName | None = None
    candidates: list[TaxonomyCandidate] = Field(default_factory=list)
    match_score: Confidence | None = None
    decision_basis: Annotated[str, Field(min_length=1, max_length=1000)]

    @property
    def canonical_name(self) -> str | None:
        """Return the canonical skill using the pre-Step-5 attribute name."""
        return self.canonical_skill

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        """Ensure mapping status, method, and accepted skill are consistent."""
        has_skill_id = self.skill_id is not None
        has_name = self.canonical_skill is not None

        if has_skill_id != has_name:
            msg = "skill_id and canonical_skill must be provided together"
            raise ValueError(msg)
        if self.status is MappingStatus.RESOLVED and not has_skill_id:
            msg = "resolved mappings require skill_id and canonical_skill"
            raise ValueError(msg)
        if self.status is not MappingStatus.RESOLVED and has_skill_id:
            msg = "unresolved mappings cannot identify an accepted taxonomy skill"
            raise ValueError(msg)
        if (
            self.match_method in {MatchMethod.EXACT, MatchMethod.ALIAS}
            and self.status is not MappingStatus.RESOLVED
        ):
            msg = "exact and alias mappings must be resolved"
            raise ValueError(msg)
        if self.match_method is MatchMethod.LLM_SELECTED and self.status not in {
            MappingStatus.RESOLVED,
            MappingStatus.NEEDS_REVIEW,
        }:
            msg = "LLM-selected mappings must be resolved or need review"
            raise ValueError(msg)
        if self.match_method is MatchMethod.UNRESOLVED and self.status not in {
            MappingStatus.NEEDS_REVIEW,
            MappingStatus.UNMAPPED,
        }:
            msg = "unresolved methods must need review or be unmapped"
            raise ValueError(msg)
        if (
            self.status is MappingStatus.RESOLVED
            and self.match_method is MatchMethod.UNRESOLVED
        ):
            msg = "resolved mappings cannot use the unresolved method"
            raise ValueError(msg)
        return self


class TaxonomyNormalizationResult(ContractModel):
    """Collection of taxonomy mappings and unresolved skill names."""

    mappings: list[TaxonomyMapping]
    unresolved_skills: list[str] = Field(default_factory=list)


class TaxonomySelection(ContractModel):
    """A selector proposal that must be verified against the repository."""

    decision: Literal["select", "needs_review", "unmapped"]
    selected_skill_id: SkillId | None = None
    candidate_skill_ids: list[SkillId] = Field(default_factory=list)
    decision_basis: Annotated[str, Field(min_length=1, max_length=1000)]
    match_score: Confidence | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        """Ensure the proposed identifiers agree with the decision."""
        if self.decision == "select" and self.selected_skill_id is None:
            msg = "select decisions require selected_skill_id"
            raise ValueError(msg)
        if self.decision == "needs_review" and len(self.candidate_skill_ids) < 2:
            msg = "needs_review decisions require at least two candidates"
            raise ValueError(msg)
        if self.decision == "needs_review" and self.selected_skill_id is not None:
            msg = "needs_review decisions cannot select a skill"
            raise ValueError(msg)
        if self.decision == "unmapped" and self.selected_skill_id is not None:
            msg = "unmapped decisions cannot select a skill"
            raise ValueError(msg)
        return self


class ExactMatchSource(str, Enum):
    """Source of a deterministic taxonomy match."""

    CANONICAL_NAME = "canonical_name"
    ALIAS = "alias"


class ExactTaxonomyMatch(ContractModel):
    """A deterministic match to a taxonomy skill."""

    model_config = ConfigDict(str_strip_whitespace=False, frozen=True)

    query: str
    skill: TaxonomySkill
    match_source: ExactMatchSource
