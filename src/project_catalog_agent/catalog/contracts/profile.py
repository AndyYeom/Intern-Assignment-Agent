"""Normalized project profile contracts."""

from typing import Annotated

from pydantic import Field

from project_catalog_agent.catalog.contracts.common import (
    ContractModel,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RequirementImportance,
)

Confidence = Annotated[
    float,
    Field(
        ge=0.0,
        le=1.0,
        description=(
            "Interpretation signal; not a proficiency level or verified probability."
        ),
    ),
]


class RequirementProvenance(ContractModel):
    """Source extraction and taxonomy decisions contributing to one skill."""

    source_requirement_index: Annotated[int, Field(ge=0)]
    raw_skill: Annotated[str, Field(min_length=1, max_length=200)]
    importance: RequirementImportance
    required_level: ProficiencyLevel | None
    evidence_text: Annotated[str, Field(min_length=1, max_length=2_000)]
    extraction_decision_basis: Annotated[str, Field(min_length=1, max_length=1_000)]
    extraction_confidence: Confidence
    match_method: MatchMethod
    taxonomy_decision_basis: Annotated[str, Field(min_length=1, max_length=1_000)]


class UnresolvedProjectRequirement(ContractModel):
    """An extracted requirement that has no accepted canonical skill."""

    source_requirement_index: Annotated[int, Field(ge=0)]
    raw_skill: Annotated[str, Field(min_length=1, max_length=200)]
    mapping_status: MappingStatus
    importance: RequirementImportance
    required_level: ProficiencyLevel | None
    evidence_text: Annotated[str, Field(min_length=1, max_length=2_000)]
    candidate_skill_ids: list[str] = Field(default_factory=list)


class ProjectRequirement(ContractModel):
    """A normalized skill requirement for a project."""

    skill_id: Annotated[str, Field(min_length=1, max_length=100)]
    canonical_name: Annotated[str, Field(min_length=1, max_length=200)]
    importance: RequirementImportance
    required_level: Annotated[
        ProficiencyLevel | None,
        Field(
            description=(
                "The level an applicant needs to complete the project work with "
                "normal mentoring."
            )
        ),
    ]
    evidence_text: Annotated[str, Field(min_length=1, max_length=2_000)]
    confidence: Confidence
    decision_basis: Annotated[str, Field(min_length=1, max_length=1_000)]
    provenance: list[RequirementProvenance] = Field(default_factory=list)


class ProjectProfile(ContractModel):
    """Catalog-ready representation of a submitted project."""

    request_id: Annotated[str, Field(min_length=1, max_length=100)]
    project_name: Annotated[str, Field(min_length=1, max_length=200)]
    project_description: Annotated[str, Field(min_length=1, max_length=20_000)]
    project_summary: Annotated[str, Field(min_length=1, max_length=2_000)]
    requirements: list[ProjectRequirement] = Field(default_factory=list)
    unresolved_skills: list[str] = Field(default_factory=list)
    unresolved_requirements: list[UnresolvedProjectRequirement] = Field(
        default_factory=list
    )
