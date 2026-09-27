"""Query helpers: the only place that knows how entities are loaded.

Agents never touch the database; services call these and hand plain data to
the agents.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import (
    AgentRun,
    Applicant,
    ApplicantRoleScore,
    ApplicantSkill,
    Assignment,
    AssignmentRun,
    Project,
    ProjectRole,
    ProjectRoleSkill,
    Skill,
)

# ---- skills ---------------------------------------------------------------


def list_skills(session: Session) -> Sequence[Skill]:
    return session.scalars(select(Skill).order_by(Skill.category, Skill.name)).all()


def skill_ids(session: Session) -> set[str]:
    return set(session.scalars(select(Skill.id)))


# ---- applicants -----------------------------------------------------------


def _applicant_options():
    return (
        selectinload(Applicant.skills).selectinload(ApplicantSkill.skill),
        selectinload(Applicant.skills).selectinload(ApplicantSkill.evidence),
        selectinload(Applicant.documents),
    )


def get_applicant(session: Session, applicant_id: uuid.UUID) -> Applicant | None:
    return session.scalars(
        select(Applicant).where(Applicant.id == applicant_id).options(*_applicant_options())
    ).one_or_none()


def get_applicant_by_email(session: Session, email: str) -> Applicant | None:
    return session.scalars(
        select(Applicant).where(func.lower(Applicant.email) == email.lower())
    ).one_or_none()


def list_applicants(
    session: Session, *, status: str | None = None, query: str | None = None
) -> Sequence[Applicant]:
    stmt = select(Applicant).options(
        selectinload(Applicant.skills).selectinload(ApplicantSkill.skill)
    )
    if status:
        stmt = stmt.where(Applicant.status == status)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                Applicant.name.ilike(like),
                Applicant.email.ilike(like),
                Applicant.reference.ilike(like),
                Applicant.github_login.ilike(like),
            )
        )
    return session.scalars(stmt.order_by(Applicant.created_at.desc(), Applicant.reference)).all()


def ready_applicants(
    session: Session, ids: Sequence[uuid.UUID] | None = None
) -> Sequence[Applicant]:
    stmt = (
        select(Applicant)
        .where(Applicant.status == "ready")
        .options(selectinload(Applicant.skills))
        .order_by(Applicant.reference)
    )
    if ids is not None:
        stmt = stmt.where(Applicant.id.in_(ids))
    return session.scalars(stmt).all()


def agent_runs_for(session: Session, applicant_id: uuid.UUID) -> Sequence[AgentRun]:
    return session.scalars(
        select(AgentRun)
        .where(AgentRun.applicant_id == applicant_id)
        .order_by(AgentRun.started_at)
    ).all()


def approved_placements(
    session: Session, *, exclude_assignment: uuid.UUID | None = None
) -> dict[uuid.UUID, Assignment]:
    """Committed placements: each applicant's approved assignment (newest if several).

    Approval is what commits a seat. Later runs skip these applicants and only
    offer each role's remaining seats; rejecting the approval releases both.
    """
    stmt = (
        select(Assignment)
        .join(AssignmentRun, Assignment.assignment_run_id == AssignmentRun.id)
        .where(Assignment.status == "approved", AssignmentRun.status == "completed")
        .order_by(Assignment.updated_at.desc())
    )
    if exclude_assignment is not None:
        stmt = stmt.where(Assignment.id != exclude_assignment)
    placed: dict[uuid.UUID, Assignment] = {}
    for row in session.scalars(stmt):
        placed.setdefault(row.applicant_id, row)
    return placed


def filled_seats(placements: dict[uuid.UUID, Assignment]) -> dict[uuid.UUID, int]:
    """Approved placements per role."""
    counts: dict[uuid.UUID, int] = {}
    for a in placements.values():
        counts[a.project_role_id] = counts.get(a.project_role_id, 0) + 1
    return counts


def latest_assignments(
    session: Session, applicant_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Assignment]:
    """Each applicant's approved placement, else their proposal from the newest
    completed run that placed them."""
    if not applicant_ids:
        return {}
    rows = session.execute(
        select(Assignment)
        .join(AssignmentRun, Assignment.assignment_run_id == AssignmentRun.id)
        .where(Assignment.applicant_id.in_(applicant_ids), AssignmentRun.status == "completed")
        .order_by(Assignment.applicant_id, AssignmentRun.created_at.desc())
    ).scalars()
    latest: dict[uuid.UUID, Assignment] = {}
    for row in rows:
        current = latest.get(row.applicant_id)
        if current is None or (row.status == "approved" and current.status != "approved"):
            latest[row.applicant_id] = row
    return latest


def latest_scores(session: Session, applicant_id: uuid.UUID) -> Sequence[ApplicantRoleScore]:
    run_id = session.scalar(
        select(ApplicantRoleScore.assignment_run_id)
        .join(AssignmentRun, ApplicantRoleScore.assignment_run_id == AssignmentRun.id)
        .where(ApplicantRoleScore.applicant_id == applicant_id, AssignmentRun.status == "completed")
        .order_by(AssignmentRun.created_at.desc())
        .limit(1)
    )
    if run_id is None:
        return []
    return session.scalars(
        select(ApplicantRoleScore)
        .where(
            ApplicantRoleScore.assignment_run_id == run_id,
            ApplicantRoleScore.applicant_id == applicant_id,
        )
        .order_by(ApplicantRoleScore.fit_score.desc())
    ).all()


# ---- projects -------------------------------------------------------------


def _project_options():
    return (
        selectinload(Project.roles)
        .selectinload(ProjectRole.requirements)
        .selectinload(ProjectRoleSkill.skill),
    )


def list_projects(session: Session, *, status: str | None = None) -> Sequence[Project]:
    stmt = select(Project).options(*_project_options()).order_by(Project.name)
    if status:
        stmt = stmt.where(Project.status == status)
    return session.scalars(stmt).all()


def get_project(session: Session, project_id: uuid.UUID) -> Project | None:
    return session.scalars(
        select(Project).where(Project.id == project_id).options(*_project_options())
    ).one_or_none()


def get_role(session: Session, role_id: uuid.UUID) -> ProjectRole | None:
    return session.scalars(
        select(ProjectRole)
        .where(ProjectRole.id == role_id)
        .options(selectinload(ProjectRole.requirements).selectinload(ProjectRoleSkill.skill))
    ).one_or_none()


def role_in_use(session: Session, role_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Assignment)
            .where(or_(Assignment.project_role_id == role_id, Assignment.solver_role_id == role_id))
        )
        or session.scalar(
            select(func.count())
            .select_from(ApplicantRoleScore)
            .where(ApplicantRoleScore.project_role_id == role_id)
        )
    )


# ---- assignment runs ------------------------------------------------------


def list_runs(session: Session) -> Sequence[AssignmentRun]:
    return session.scalars(select(AssignmentRun).order_by(AssignmentRun.created_at.desc())).all()


def get_run(session: Session, run_id: uuid.UUID) -> AssignmentRun | None:
    return session.get(AssignmentRun, run_id)


def run_assignments(session: Session, run_id: uuid.UUID) -> Sequence[Assignment]:
    return session.scalars(
        select(Assignment).where(Assignment.assignment_run_id == run_id)
    ).all()


def run_scores(session: Session, run_id: uuid.UUID) -> Sequence[ApplicantRoleScore]:
    return session.scalars(
        select(ApplicantRoleScore).where(ApplicantRoleScore.assignment_run_id == run_id)
    ).all()


def assigned_counts(session: Session, run_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = session.execute(
        select(Assignment.assignment_run_id, func.count())
        .where(Assignment.assignment_run_id.in_(run_ids), Assignment.status != "rejected")
        .group_by(Assignment.assignment_run_id)
    )
    return {run_id: count for run_id, count in rows}
