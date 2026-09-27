"""Turn agent output into resolved, taxonomy-keyed applicant skills.

Pure functions: no database or network. The level arithmetic is the existing
pipeline/resolve_profile.py; this module only joins its inputs and outputs on
taxonomy ids, so the database stores exactly what scoring consumes.
"""

from dataclasses import dataclass, field
from typing import Any

from pipeline.resolve_profile import resolve_profile

from src.evidence_agent.claims import to_skill_id


@dataclass
class EvidenceItem:
    source_type: str  # resume | portfolio | github
    reference: str | None
    excerpt: str | None
    level: int | None = None
    details: dict[str, Any] | None = None


@dataclass
class ResolvedSkill:
    skill_id: str
    final_level: int
    claimed_level: int | None
    observed_level: int | None = None
    verification_status: str | None = None
    evidence_strength: str | None = None
    flag: str | None = None
    confidence: float | None = None
    claim_summary: str | None = None
    verification_summary: str | None = None
    method: str | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)


def _github_evidence(verification: dict[str, Any]) -> list[EvidenceItem]:
    items = []
    for repo in verification.get("repos") or []:
        reasons = repo.get("reasons") or []
        items.append(
            EvidenceItem(
                source_type="github",
                reference=repo.get("html_url"),
                excerpt="; ".join(reasons) or None,
                level=repo.get("level"),
                details={"repo": repo.get("repo")},
            )
        )
    if not items:
        items = [
            EvidenceItem(source_type="github", reference=url, excerpt=None)
            for url in verification.get("repo_links") or []
        ]
    return items


def resolve_skills(
    claims: list[dict[str, Any]], verifications: list[dict[str, Any]]
) -> tuple[list[ResolvedSkill], list[str]]:
    """Resolve claims against GitHub verifications.

    claims: profile-agent skills (canonical_skill, claimed_level, confidence,
        reasoning, evidence[{source, text, page}]).
    verifications: evidence-agent SkillVerification dicts keyed by skill_id
        (status, observed_level, evidence_strength, rationale, repos, method).
        Empty when GitHub evidence is unavailable: every claim then stays at its
        claimed level and is flagged "unverified" by resolve_profile.

    Returns the resolved skills and the claim names that match no taxonomy skill.
    """
    by_id: dict[str, dict[str, Any]] = {}
    unmapped: list[str] = []
    for claim in claims:
        skill_id = to_skill_id(claim["canonical_skill"])
        if skill_id is None:
            unmapped.append(claim["canonical_skill"])
            continue
        current = by_id.get(skill_id)
        # Two spellings of one skill: keep the lower claim, like the evidence agent.
        if current is None or claim["claimed_level"] < current["claimed_level"]:
            by_id[skill_id] = claim

    checks = {v["skill_id"]: v for v in verifications}
    resolved = resolve_profile(
        {
            "applicant_id": "-",
            "skills": [
                {"canonical_skill": sid, "claimed_level": c["claimed_level"]}
                for sid, c in by_id.items()
            ],
        },
        {
            "skill_verification": [
                {
                    "canonical_skill": sid,
                    "github_observed_level": v.get("observed_level") or 0,
                    "verification_status": v["status"],
                }
                for sid, v in checks.items()
                if sid in by_id
            ]
        },
    )

    skills = []
    for skill_id, claim in by_id.items():
        verification = checks.get(skill_id, {})
        evidence = [
            EvidenceItem(
                source_type=e.get("source", "resume"),
                reference=f"page {e['page']}" if e.get("page") else None,
                excerpt=e.get("text"),
            )
            for e in claim.get("evidence") or []
        ]
        evidence += _github_evidence(verification)
        skills.append(
            ResolvedSkill(
                skill_id=skill_id,
                final_level=resolved["skills"][skill_id],
                claimed_level=claim["claimed_level"],
                observed_level=verification.get("observed_level"),
                verification_status=verification.get("status"),
                evidence_strength=verification.get("evidence_strength"),
                flag=resolved["flags"].get(skill_id),
                confidence=claim.get("confidence"),
                claim_summary=claim.get("reasoning"),
                verification_summary=verification.get("rationale"),
                method=verification.get("method"),
                evidence=evidence,
            )
        )
    return skills, unmapped
