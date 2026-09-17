from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SkillEvidence(BaseModel):
    source: Literal["resume", "portfolio"]
    text: str = Field(
        min_length=1,
        description="Exact short excerpt supporting the proficiency score.",
    )
    page: int | None = Field(
        default=None,
        ge=1,
        description="Page number when explicitly available; otherwise null.",
    )


class ApplicantSkill(BaseModel):
    canonical_skill: str = Field(min_length=1)
    category: str = Field(min_length=1)
    claimed_level: Literal[1, 2, 3]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[SkillEvidence] = Field(min_length=1, default_factory=list)
    reasoning: str = Field(
        min_length=1,
        description="Short evidence-based justification, not chain-of-thought.",
    )


class EducationRecord(BaseModel):
    institution: str = Field(min_length=1)
    qualification: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None


class WorkExperienceRecord(BaseModel):
    organization: str = Field(min_length=1)
    role: str = Field(min_length=1)
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    demonstrated_skills: list[str] = Field(default_factory=list)


class ApplicantProfile(BaseModel):
    applicant_id: str = Field(min_length=1)
    skills: list[ApplicantSkill] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    education: list[EducationRecord] = Field(default_factory=list)
    work_experience: list[WorkExperienceRecord] = Field(default_factory=list)
