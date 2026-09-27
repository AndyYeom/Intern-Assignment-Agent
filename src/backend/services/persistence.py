"""Write resolved skills and taxonomy rows."""

import json
from pathlib import Path

from sqlalchemy import delete
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


def replace_applicant_skills(
    session: Session, applicant: Applicant, skills: list[ResolvedSkill]
) -> None:
    """Replace the applicant's skills with a fresh resolution (a re-run supersedes)."""
    session.execute(delete(ApplicantSkill).where(ApplicantSkill.applicant_id == applicant.id))
    session.flush()
    for resolved in skills:
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
            )
            for e in resolved.evidence
        ]
        session.add(row)
    session.flush()
