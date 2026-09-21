"""GitHub observations, then claimed level vs observed level per skill.

Two steps, so the first can run beside the profile agent:

  observe_all(github)        -> GitHubObservation   (needs no claims)
  judge(claims, observation) -> EvidenceReport

  verified            GitHub supports the claimed level or higher
  partially_verified  the skill is there, one level below the claim
  conflicting         the skill is there, two levels below the claim
  not_observed        nothing on GitHub to judge; absence is not a penalty
"""
from __future__ import annotations

from collections import Counter

from generator.schemas import GitHubProfile

from .evidence_models import (
    ApplicantProfile,
    EvidenceReport,
    GitHubObservation,
    ObservedSkill,
    RepoEvidence,
    SkillVerification,
    Status,
)
from .observe import observe, observed_skills

LEVEL_NAMES = {1: "Entry", 2: "Intermediate", 3: "Advanced"}


def observe_all(github: GitHubProfile) -> GitHubObservation:
    skills, weak_only = [], []
    for skill_id in observed_skills(github):
        obs = observe(github, skill_id)
        if obs.level is None:
            if obs.weak_only:
                weak_only.append(skill_id)
            continue
        skills.append(ObservedSkill(
            skill_id=skill_id,
            observed_level=obs.level,
            evidence_strength=obs.strength,
            repo_links=[repo.html_url for repo, _, _ in obs.repos],
            repos=[RepoEvidence(repo=repo.full_name, html_url=repo.html_url,
                                level=level, reasons=reasons)
                   for repo, level, reasons in obs.repos],
        ))
    return GitHubObservation(applicant_id=github.applicant_id, github_login=github.login,
                             profile_tier=github.tier, skills=skills, weak_only=weak_only)


def judge(claims: ApplicantProfile, observation: GitHubObservation) -> EvidenceReport:
    if claims.applicant_id != observation.applicant_id:
        raise ValueError(f"claims for {claims.applicant_id} paired with "
                         f"GitHub evidence for {observation.applicant_id}")

    results = []
    for claim in sorted(claims.skills, key=lambda c: c.skill_id):
        seen = observation.get(claim.skill_id)
        claimed = LEVEL_NAMES[claim.level]
        status: Status
        if seen is None:
            status = "not_observed"
            why = ("only self-declared signals (repo name or topic)"
                   if claim.skill_id in observation.weak_only else "no repository shows this skill")
            rationale = f"Claimed {claimed}; {why}. Absence is not evidence against the claim."
        else:
            gap = claim.level - seen.observed_level
            status = ("verified" if gap <= 0 else
                      "partially_verified" if gap == 1 else "conflicting")
            rationale = (f"Claimed {claimed}; GitHub evidence supports "
                         f"{LEVEL_NAMES[seen.observed_level]} ({len(seen.repos)} repo(s)).")
        results.append(SkillVerification(
            skill_id=claim.skill_id,
            source_names=claim.source_names,
            claimed_level=claim.level,
            status=status,
            observed_level=seen.observed_level if seen else None,
            evidence_strength=seen.evidence_strength if seen else
            ("weak" if claim.skill_id in observation.weak_only else "none"),
            repo_links=seen.repo_links if seen else [],
            repos=seen.repos if seen else [],
            rationale=rationale,
        ))

    claimed_ids = {c.skill_id for c in claims.skills}
    return EvidenceReport(
        applicant_id=observation.applicant_id,
        github_login=observation.github_login,
        profile_tier=observation.profile_tier,
        claims_source=claims.source,
        skills=results,
        unclaimed_observed=[s for s in observation.skills if s.skill_id not in claimed_ids],
        unmapped_claims=claims.unmapped,
        status_counts=dict(sorted(Counter(r.status for r in results).items())),
    )


def verify(claims: ApplicantProfile, github: GitHubProfile) -> EvidenceReport:
    if claims.applicant_id != github.applicant_id:
        raise ValueError(f"claims for {claims.applicant_id} paired with "
                         f"GitHub profile {github.applicant_id}")
    return judge(claims, observe_all(github))
