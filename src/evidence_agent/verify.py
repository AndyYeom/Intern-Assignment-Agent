"""Claimed level vs observed level -> a verification status per skill.

  verified            GitHub supports the claimed level or higher
  partially_verified  the skill is there, one level below the claim
  conflicting         the skill is there, two levels below the claim
  not_observed        nothing on GitHub to judge; absence is not a penalty
"""
from __future__ import annotations

from collections import Counter

from generator.schemas import GitHubProfile

from .observe import observe, observed_skills
from .schemas import (
    ApplicantProfile,
    EvidenceReport,
    ObservedSkill,
    RepoEvidence,
    SkillVerification,
)

LEVEL_NAMES = {1: "Entry", 2: "Intermediate", 3: "Advanced"}


def verify(claims: ApplicantProfile, github: GitHubProfile) -> EvidenceReport:
    if claims.applicant_id != github.applicant_id:
        raise ValueError(f"claims for {claims.applicant_id} paired with "
                         f"GitHub profile {github.applicant_id}")

    results = []
    for claim in sorted(claims.skills, key=lambda c: c.skill_id):
        obs = observe(github, claim.skill_id)
        claimed = LEVEL_NAMES[claim.level]
        if obs.level is None:
            status = "not_observed"
            why = ("only self-declared signals (repo name or topic)" if obs.weak_only
                   else "no repository shows this skill")
            rationale = f"Claimed {claimed}; {why}. Absence is not evidence against the claim."
        else:
            gap = claim.level - obs.level
            status = ("verified" if gap <= 0 else
                      "partially_verified" if gap == 1 else "conflicting")
            rationale = (f"Claimed {claimed}; GitHub evidence supports "
                         f"{LEVEL_NAMES[obs.level]} ({len(obs.repos)} repo(s)).")
        results.append(SkillVerification(
            skill_id=claim.skill_id,
            claimed_level=claim.level,
            status=status,
            observed_level=obs.level,
            evidence_strength=obs.strength,
            repo_links=[repo.html_url for repo, _, _ in obs.repos],
            repos=[RepoEvidence(repo=repo.full_name, html_url=repo.html_url,
                                level=level, reasons=reasons)
                   for repo, level, reasons in obs.repos],
            rationale=rationale,
        ))

    claimed_ids = {c.skill_id for c in claims.skills}
    unclaimed = []
    for skill_id in observed_skills(github):
        if skill_id in claimed_ids:
            continue
        obs = observe(github, skill_id)
        if obs.level is not None:
            unclaimed.append(ObservedSkill(
                skill_id=skill_id, observed_level=obs.level, evidence_strength=obs.strength,
                repo_links=[repo.html_url for repo, _, _ in obs.repos]))

    return EvidenceReport(
        applicant_id=github.applicant_id,
        github_login=github.login,
        profile_tier=github.tier,
        claims_source=claims.source,
        skills=results,
        unclaimed_observed=unclaimed,
        status_counts=dict(sorted(Counter(r.status for r in results).items())),
    )
