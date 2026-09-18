"""Contracts for the evidence agent.

In:  `ApplicantProfile` (the profile agent's output: claimed skills and levels)
     + `GitHubProfile` (generator/schemas.py).
Out: `EvidenceReport`, one `SkillVerification` per claimed skill.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["verified", "partially_verified", "not_observed", "conflicting"]
Strength = Literal["none", "weak", "moderate", "strong"]


class SkillClaim(BaseModel):
    skill_id: str
    level: int = Field(ge=1, le=3)
    evidence_quote: str | None = None
    reasoning: str | None = None


class ApplicantProfile(BaseModel):
    applicant_id: str
    skills: list[SkillClaim] = Field(default_factory=list)
    unmapped: list[str] = Field(default_factory=list)
    source: str = "profile_agent"


class RepoEvidence(BaseModel):
    repo: str
    html_url: str
    level: int
    reasons: list[str] = Field(default_factory=list)


class SkillVerification(BaseModel):
    skill_id: str
    claimed_level: int
    status: Status
    observed_level: int | None      # None: GitHub shows nothing to judge
    evidence_strength: Strength
    repo_links: list[str] = Field(default_factory=list)
    repos: list[RepoEvidence] = Field(default_factory=list)
    rationale: str


class ObservedSkill(BaseModel):
    """Evidenced on GitHub but not claimed: useful to the resolver, never a penalty."""

    skill_id: str
    observed_level: int
    evidence_strength: Strength
    repo_links: list[str] = Field(default_factory=list)


class EvidenceReport(BaseModel):
    applicant_id: str
    github_login: str
    profile_tier: str
    claims_source: str
    skills: list[SkillVerification] = Field(default_factory=list)
    unclaimed_observed: list[ObservedSkill] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)
