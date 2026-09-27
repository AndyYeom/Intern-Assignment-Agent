"""Write resolved skills and taxonomy rows."""

import json
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy import true as sa_true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.db.models import Applicant, ApplicantSkill, ApplicantSkillEvidence, Skill
from backend.services.skill_resolution import ResolvedSkill


def upsert_taxonomy(session: Session, taxonomy_path: Path) -> tuple[int, int]:
    """Insert or update every taxonomy skill. Returns (inserted, updated)."""
    data = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    existing = {s.id: s for s in session.query(Skill).all()}
    inserted = updated = 0
    for item in data["skills"]:
        values = {
            "id": item["id"],
            "name": item["name"],
            "category": item["category"],
            "aliases": sorted(set(item.get("aliases", []))),
        }
        current = existing.get(item["id"])
        if current is None:
            session.execute(insert(Skill).values(**values))
            inserted += 1
        elif (current.name, current.category, sorted(current.aliases)) != (
            values["name"],
            values["category"],
            values["aliases"],
        ):
            current.name, current.category, current.aliases = (
                values["name"],
                values["category"],
                values["aliases"],
            )
            updated += 1
    session.flush()
    return inserted, updated


def pinned_skill_ids(session: Session, applicant: Applicant) -> set[str]:
    """Skills a manager added, edited or deleted: reprocessing leaves them alone."""
    rows = session.scalars(
        select(ApplicantSkill).where(ApplicantSkill.applicant_id == applicant.id)
    )
    return {row.skill_id for row in rows if row.pinned}


def replace_applicant_skills(
    session: Session, applicant: Applicant, skills: list[ResolvedSkill]
) -> None:
    """Replace the applicant's agent-derived skills with a fresh resolution.

    A re-run supersedes the previous agent output, but never a manager's
    override: pinned skills (added, edited or soft-deleted by a manager) keep
    exactly what the manager left, including their evidence.
    """
    pinned = pinned_skill_ids(session, applicant)
    session.execute(
        delete(ApplicantSkill).where(
            ApplicantSkill.applicant_id == applicant.id,
            ApplicantSkill.skill_id.not_in(pinned) if pinned else sa_true(),
        )
    )
    session.flush()
    for resolved in skills:
        if resolved.skill_id in pinned:
            continue
        row = ApplicantSkill(
            applicant_id=applicant.id,
            skill_id=resolved.skill_id,
            final_level=resolved.final_level,
            claimed_level=resolved.claimed_level,
            observed_level=resolved.observed_level,
            verification_status=resolved.verification_status,
            evidence_strength=resolved.evidence_strength,
            flag=resolved.flag,
            confidence=resolved.confidence,
            claim_summary=resolved.claim_summary,
            verification_summary=resolved.verification_summary,
            method=resolved.method,
        )
        row.evidence = [
            ApplicantSkillEvidence(
                source_type=e.source_type,
                reference=e.reference,
                excerpt=e.excerpt,
                level=e.level,
                details=e.details,
                position=i,
            )
            for i, e in enumerate(resolved.evidence)
        ]
        session.add(row)
    session.flush()
