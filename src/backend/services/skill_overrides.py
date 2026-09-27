"""Manager overrides of an applicant's resolved skills and their evidence.

Every change pins the skill (see ApplicantSkill.pinned), so reprocessing and
the legacy import never overwrite a manager's decision. Deletes are soft:
rows keep their data and get deleted_at, and every reader skips them.

Changing a claimed or observed level re-derives the verification status, flag
and final level with the pipeline's own rules (pipeline/resolve_profile.py),
so a manager's observation is treated exactly like the evidence agent's.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pipeline.resolve_profile import resolve_skill
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Applicant, ApplicantSkill, ApplicantSkillEvidence, Skill


class OverrideError(ValueError):
    """The change cannot be applied; the message is shown to the manager."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _now() -> datetime:
    return datetime.now(UTC)


def verification_status(claimed: int | None, observed: int | None) -> str | None:
    """The evidence agent's verdict rule (src/evidence_agent/verify.py)."""
    if claimed is None:
        return None
    if observed is None:
        return "not_observed"
    if observed >= claimed:
        return "verified"
    if observed == claimed - 1:
        return "partially_verified"
    return "conflicting"


def rederive(row: ApplicantSkill) -> None:
    """Recompute status, flag and final level from the claimed/observed pair."""
    status = verification_status(row.claimed_level, row.observed_level)
    row.verification_status = status
    if status is None:
        # No claim (an observed-only skill): the observation is all there is.
        row.final_level, row.flag = row.observed_level or 0, None
    else:
        row.final_level, row.flag = resolve_skill(row.claimed_level, row.observed_level or 0, status)
    row.method = "manager"


def _applicant(session: Session, applicant_id: uuid.UUID) -> Applicant:
    applicant = session.get(Applicant, applicant_id)
    if applicant is None:
        raise OverrideError(404, "not_found", "Applicant not found.")
    if applicant.status == "processing":
        raise OverrideError(
            409, "already_processing", "This applicant is being processed; edit skills when it finishes."
        )
    return applicant


def _any_row(session: Session, applicant_id: uuid.UUID, skill_id: str) -> ApplicantSkill | None:
    """The applicant's row for a skill, including a soft-deleted one."""
    return session.scalar(
        select(ApplicantSkill).where(
            ApplicantSkill.applicant_id == applicant_id, ApplicantSkill.skill_id == skill_id
        )
    )


def active_skill(session: Session, applicant_id: uuid.UUID, skill_id: str) -> ApplicantSkill:
    _applicant(session, applicant_id)
    row = _any_row(session, applicant_id, skill_id)
    if row is None or row.deleted_at is not None:
        raise OverrideError(404, "not_found", "Skill not found for this applicant.")
    return row


def update_skill(session: Session, applicant_id: uuid.UUID, skill_id: str, changes: dict[str, Any]) -> ApplicantSkill:
    """Apply only the fields present in `changes` (None clears observed_level)."""
    row = active_skill(session, applicant_id, skill_id)
    levels_changed = False
    for field in ("claimed_level", "observed_level"):
        if field in changes and getattr(row, field) != changes[field]:
            setattr(row, field, changes[field])
            levels_changed = True
    for field in ("claim_summary", "verification_summary"):
        if field in changes:
            setattr(row, field, changes[field] or None)
    if levels_changed:
        rederive(row)
    row.edited_at = _now()
    session.flush()
    return row


def add_skill(session: Session, applicant_id: uuid.UUID, data: dict[str, Any]) -> ApplicantSkill:
    """Add a skill as the manager. Re-adding a soft-deleted skill restores that row."""
    _applicant(session, applicant_id)
    if session.get(Skill, data["skill_id"]) is None:
        raise OverrideError(422, "unknown_skill", f"Unknown skill '{data['skill_id']}'.")
    row = _any_row(session, applicant_id, data["skill_id"])
    if row is not None and row.deleted_at is None:
        raise OverrideError(409, "duplicate_skill", "This applicant already has that skill.")
    if row is None:
        row = ApplicantSkill(applicant_id=applicant_id, skill_id=data["skill_id"], final_level=0)
        session.add(row)
    else:
        # Restore: the old evidence stays soft-deleted; the manager starts clean.
        for ev in session.scalars(
            select(ApplicantSkillEvidence).where(ApplicantSkillEvidence.applicant_skill_id == row.id)
        ):
            ev.deleted_at = ev.deleted_at or _now()
        row.deleted_at = None
        row.evidence_strength = row.confidence = None
    row.source = "manager"
    row.claimed_level = data["claimed_level"]
    row.observed_level = data.get("observed_level")
    row.claim_summary = data.get("claim_summary") or None
    row.verification_summary = data.get("verification_summary") or None
    rederive(row)
    row.edited_at = _now()
    session.flush()
    session.refresh(row)
    return row


def delete_skill(session: Session, applicant_id: uuid.UUID, skill_id: str) -> None:
    row = active_skill(session, applicant_id, skill_id)
    row.deleted_at = row.edited_at = _now()
    session.flush()


def _evidence(session: Session, row: ApplicantSkill, evidence_id: uuid.UUID) -> ApplicantSkillEvidence:
    ev = session.get(ApplicantSkillEvidence, evidence_id)
    if ev is None or ev.applicant_skill_id != row.id or ev.deleted_at is not None:
        raise OverrideError(404, "not_found", "Evidence not found for this skill.")
    return ev


def add_evidence(
    session: Session, applicant_id: uuid.UUID, skill_id: str, data: dict[str, Any]
) -> ApplicantSkillEvidence:
    row = active_skill(session, applicant_id, skill_id)
    last = session.scalar(
        select(func.max(ApplicantSkillEvidence.position)).where(
            ApplicantSkillEvidence.applicant_skill_id == row.id
        )
    )
    ev = ApplicantSkillEvidence(
        applicant_skill_id=row.id,
        source_type=data.get("source_type") or "manager",
        reference=data.get("reference") or None,
        excerpt=data.get("excerpt") or None,
        level=data.get("level"),
        position=(last if last is not None else -1) + 1,
        edited_at=_now(),
    )
    session.add(ev)
    row.edited_at = _now()
    session.flush()
    return ev


def update_evidence(
    session: Session, applicant_id: uuid.UUID, skill_id: str, evidence_id: uuid.UUID, changes: dict[str, Any]
) -> ApplicantSkillEvidence:
    row = active_skill(session, applicant_id, skill_id)
    ev = _evidence(session, row, evidence_id)
    for field in ("source_type", "reference", "excerpt", "level"):
        if field in changes:
            value = changes[field]
            if field == "source_type" and not value:
                raise OverrideError(422, "invalid_source", "Evidence needs a source type.")
            setattr(ev, field, value if field in ("level", "source_type") else (value or None))
    ev.edited_at = row.edited_at = _now()
    session.flush()
    return ev


def delete_evidence(session: Session, applicant_id: uuid.UUID, skill_id: str, evidence_id: uuid.UUID) -> None:
    row = active_skill(session, applicant_id, skill_id)
    ev = _evidence(session, row, evidence_id)
    ev.deleted_at = row.edited_at = _now()
    session.flush()
