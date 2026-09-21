"""Contracts for the evidence agent.

In:  `ApplicantProfile` (the profile agent's claimed skills and levels)
     + `GitHubProfile` (generator/schemas.py).
Out: `EvidenceReport`, one `SkillVerification` per claimed skill, and
     `payload()` in the shape pipeline/resolve_profile.py reads.

Every skill is a taxonomy.json id. Nothing else is a skill.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["verified", "partially_verified", "not_observed", "conflicting"]
Strength = Literal["none", "weak", "moderate", "strong"]


class SkillClaim(BaseModel):
    skill_id: str
    level: int = Field(ge=1, le=3)
    evidence_quote: str | None = None
    reasoning: str | None = None
    # The profile agent's own names for this skill, with the level claimed under
    # each. Its downstream join (resolve_profile) matches on these, not on ids.
    source_names: dict[str, int] = Field(default_factory=dict)


def status_for(claimed: int, observed: int | None) -> Status:
    if observed is None:
        return "not_observed"
    gap = claimed - observed
    return "verified" if gap <= 0 else "partially_verified" if gap == 1 else "conflicting"


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


class ObservedSkill(BaseModel):
    """What GitHub shows for one skill, before any claim is looked at."""

    skill_id: str
    observed_level: int
    evidence_strength: Strength
    repo_links: list[str] = Field(default_factory=list)
    repos: list[RepoEvidence] = Field(default_factory=list)


class GitHubObservation(BaseModel):
    """The evidence branch's output. Needs no claims, so it runs beside the profile agent."""

    applicant_id: str
    github_login: str
    profile_tier: str
    skills: list[ObservedSkill] = Field(default_factory=list)
    # Named only by a repo name or topic: never enough to judge a level.
    weak_only: list[str] = Field(default_factory=list)

    def get(self, skill_id: str) -> ObservedSkill | None:
        return next((s for s in self.skills if s.skill_id == skill_id), None)


class LLMSkillVerdict(BaseModel):
    """One verdict as the model returns it. Status is not asked for: it follows from levels."""

    skill_id: str = Field(min_length=1)
    observed_level: Literal[1, 2, 3] | None = Field(
        description="Level the GitHub evidence supports; null when no repository shows the skill.")
    evidence_strength: Strength
    repo_links: list[str] = Field(
        default_factory=list, description="Repository URLs from the evidence, exactly as given.")
    rationale: str = Field(min_length=1, description="One or two sentences tied to the evidence.")


class LLMEvidenceOutput(BaseModel):
    applicant_id: str = Field(min_length=1)
    skills: list[LLMSkillVerdict] = Field(default_factory=list)


class SkillVerification(BaseModel):
    skill_id: str
    source_names: dict[str, int] = Field(default_factory=dict)
    claimed_level: int
    status: Status
    observed_level: int | None      # None: GitHub shows nothing to judge
    evidence_strength: Strength
    repo_links: list[str] = Field(default_factory=list)
    repos: list[RepoEvidence] = Field(default_factory=list)
    rationale: str
    # "llm": the model's verdict, checked against the rules. "rules": the
    # deterministic verdict, because the model was unavailable or unusable here.
    method: Literal["llm", "rules"] = "rules"
    # The rules' reading is always kept, so every model verdict can be compared with it.
    rule_observed_level: int | None = None
    rule_status: Status | None = None
    notes: list[str] = Field(default_factory=list)


class EvidenceTrace(BaseModel):
    """How the report was produced: which skills the model saw, what it cost."""

    model: str | None = None
    # Claims the rules could not settle; sent to the model when it is available.
    skills_needing_model: list[str] = Field(default_factory=list)
    skills_sent_to_model: list[str] = Field(default_factory=list)
    skills_decided_by_rules: dict[str, str] = Field(default_factory=dict)
    repos_sent_to_model: list[str] = Field(default_factory=list)
    prompt_chars: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_error: str | None = None


class EvidenceReport(BaseModel):
    applicant_id: str
    github_login: str
    profile_tier: str
    claims_source: str
    skills: list[SkillVerification] = Field(default_factory=list)
    unclaimed_observed: list[ObservedSkill] = Field(default_factory=list)
    unmapped_claims: list[str] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)
    mode: Literal["llm", "rules", "mixed"] = "rules"
    trace: EvidenceTrace = Field(default_factory=EvidenceTrace)

    def payload(self) -> dict[str, Any]:
        """The orchestrator's evidence contract, keyed by applicant_id like the profile's."""
        return {
            "applicant_id": self.applicant_id,
            # One entry per name the profile agent used, keyed by that exact name so
            # resolve_profile can join it; skill_id is the taxonomy id behind it.
            "skill_verification": [
                {
                    "canonical_skill": name,
                    "skill_id": s.skill_id,
                    "claimed_level": claimed,
                    "github_observed_level": s.observed_level,
                    "verification_status": status_for(claimed, s.observed_level),
                    "evidence_strength": s.evidence_strength,
                    "repo_links": s.repo_links,
                    "rationale": s.rationale,
                    "method": s.method,
                    "rule_observed_level": s.rule_observed_level,
                    "notes": s.notes,
                }
                for s in self.skills
                for name, claimed in (s.source_names or {s.skill_id: s.claimed_level}).items()
            ],
            "unclaimed_observed": [
                {"canonical_skill": s.skill_id, "github_observed_level": s.observed_level,
                 "evidence_strength": s.evidence_strength, "repo_links": s.repo_links}
                for s in self.unclaimed_observed
            ],
            "unmapped_claims": self.unmapped_claims,
        }
