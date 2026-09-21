"""Requirement extraction contracts."""

from typing import Annotated

from pydantic import Field

from project_catalog_agent.catalog.contracts.common import (
    ContractModel,
    ProficiencyLevel,
    RequirementImportance,
)

SkillText = Annotated[str, Field(min_length=1, max_length=200)]
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
EvidenceText = Annotated[str, Field(min_length=1, max_length=2_000)]
DecisionBasis = Annotated[str, Field(min_length=1, max_length=1_000)]


class ExtractedRequirement(ContractModel):
    """A requirement extracted from a project description."""

    raw_skill: SkillText
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
    confidence: Confidence
    evidence_text: EvidenceText
    decision_basis: DecisionBasis


class RequirementExtractionResult(ContractModel):
    """Structured result of requirement extraction."""

    project_summary: Annotated[str, Field(min_length=1, max_length=2_000)]
    requirements: list[ExtractedRequirement]
    uncertainties: list[str] = Field(default_factory=list)
