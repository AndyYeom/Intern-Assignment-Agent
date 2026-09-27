"""Manager API: applicants, projects/roles and assignment runs. No auth yet (MVP)."""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend import repositories as repo
from backend.api import schemas as s
from backend.api import serializers as ser
from backend.api.deps import db_session, storage
from backend.api.errors import ApiError, not_found
from backend.db.models import (
    AgentRun,
    Applicant,
    ApplicantDocument,
    ApplicantSkill,
    Assignment,
    Project,
    ProjectRole,
    ProjectRoleSkill,
)
from backend.services import assignment as assign
from backend.services import skill_overrides as overrides
from backend.services.processing import (
    GitHubUnavailable,
    check_github_available,
    latest_profile_output,
    process_applicant,
    reverify_github,
)
from backend.storage import Storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/manager", tags=["manager"])
DB = Annotated[Session, Depends(db_session)]


def _names(session: Session) -> dict:
    projects = repo.list_projects(session)
    return {
        "projects": {p.id: p.name for p in projects},
        "roles": {r.id: r.name for p in projects for r in p.roles},
    }


# ---- skills ---------------------------------------------------------------


@router.get("/skills", response_model=list[s.SkillOut])
def list_skills(session: DB) -> list[s.SkillOut]:
    return [s.SkillOut.model_validate(k) for k in repo.list_skills(session)]


# ---- applicants -----------------------------------------------------------


@router.get("/applicants", response_model=list[s.ApplicantListItem])
def list_applicants(
    session: DB,
    status: Annotated[s.ApplicantStatus | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    # assigned = has an approved placement; unassigned = does not.
    placement: Annotated[Literal["assigned", "unassigned"] | None, Query()] = None,
) -> list[s.ApplicantListItem]:
    applicants = repo.list_applicants(session, status=status, query=q)
    if placement is not None:
        placed = repo.approved_placements(session)
        applicants = [a for a in applicants if (a.id in placed) == (placement == "assigned")]
    latest = repo.latest_assignments(session, [a.id for a in applicants])
    names = _names(session)
    return [ser.applicant_item(a, latest.get(a.id), names) for a in applicants]


@router.get("/applicants/{applicant_id}", response_model=s.ApplicantDetail)
def get_applicant(applicant_id: uuid.UUID, session: DB) -> s.ApplicantDetail:
    applicant = repo.get_applicant(session, applicant_id)
    if applicant is None:
        raise not_found("Applicant")
    return ser.applicant_detail(
        applicant,
        repo.latest_assignments(session, [applicant.id]).get(applicant.id),
        list(repo.agent_runs_for(session, applicant.id)),
        list(repo.latest_scores(session, applicant.id)),
        _names(session),
    )


@router.get("/applicants/{applicant_id}/documents/{document_id}")
def download_document(
    applicant_id: uuid.UUID,
    document_id: uuid.UUID,
    session: DB,
    store: Annotated[Storage, Depends(storage)],
) -> StreamingResponse:
    doc = session.get(ApplicantDocument, document_id)
    if doc is None or doc.applicant_id != applicant_id or not store.exists(doc.storage_key):
        raise not_found("Document")
    safe_name = doc.original_filename.replace('"', "")
    return StreamingResponse(
        store.open(doc.storage_key),
        media_type=doc.mime_type,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.post(
    "/applicants/{applicant_id}/reprocess", response_model=s.ApplicationCreated, status_code=202
)
def reprocess_applicant(
    applicant_id: uuid.UUID, session: DB, background: BackgroundTasks
) -> s.ApplicationCreated:
    applicant = repo.get_applicant(session, applicant_id)
    if applicant is None:
        raise not_found("Applicant")
    if applicant.status == "processing":
        raise ApiError(409, "already_processing", "This applicant is already being processed.")
    if not any(d.document_type == "resume" for d in applicant.documents):
        raise ApiError(409, "no_resume", "This applicant has no resume on file.")
    applicant.status, applicant.status_detail = "processing", None
    session.commit()
    background.add_task(process_applicant, applicant.id)
    return s.ApplicationCreated(id=applicant.id, status="processing")


# ---- manager overrides of skills and evidence --------------------------------


def _override(session: Session, fn, *args):
    try:
        result = fn(session, *args)
    except overrides.OverrideError as exc:
        session.rollback()
        raise ApiError(exc.status, exc.code, str(exc)) from None
    session.commit()
    return result


def _skill_response(session: Session, applicant_id: uuid.UUID, skill_id: str) -> s.ApplicantSkillOut:
    row = overrides.active_skill(session, applicant_id, skill_id)
    session.refresh(row)
    return ser.skill_out(row)


@router.post("/applicants/{applicant_id}/skills", response_model=s.ApplicantSkillOut, status_code=201)
def add_applicant_skill(applicant_id: uuid.UUID, body: s.SkillCreate, session: DB) -> s.ApplicantSkillOut:
    row = _override(session, overrides.add_skill, applicant_id, body.model_dump())
    return _skill_response(session, applicant_id, row.skill_id)


@router.patch("/applicants/{applicant_id}/skills/{skill_id}", response_model=s.ApplicantSkillOut)
def update_applicant_skill(
    applicant_id: uuid.UUID, skill_id: str, body: s.SkillPatch, session: DB
) -> s.ApplicantSkillOut:
    _override(session, overrides.update_skill, applicant_id, skill_id, body.model_dump(exclude_unset=True))
    return _skill_response(session, applicant_id, skill_id)


@router.delete("/applicants/{applicant_id}/skills/{skill_id}", status_code=204)
def delete_applicant_skill(applicant_id: uuid.UUID, skill_id: str, session: DB) -> Response:
    _override(session, overrides.delete_skill, applicant_id, skill_id)
    return Response(status_code=204)


@router.post(
    "/applicants/{applicant_id}/skills/{skill_id}/evidence",
    response_model=s.EvidenceOut,
    status_code=201,
)
def add_skill_evidence(
    applicant_id: uuid.UUID, skill_id: str, body: s.EvidenceCreate, session: DB
) -> s.EvidenceOut:
    ev = _override(session, overrides.add_evidence, applicant_id, skill_id, body.model_dump())
    return ser.evidence_out(ev)


@router.patch(
    "/applicants/{applicant_id}/skills/{skill_id}/evidence/{evidence_id}", response_model=s.EvidenceOut
)
def update_skill_evidence(
    applicant_id: uuid.UUID, skill_id: str, evidence_id: uuid.UUID, body: s.EvidencePatch, session: DB
) -> s.EvidenceOut:
    ev = _override(
        session, overrides.update_evidence, applicant_id, skill_id, evidence_id,
        body.model_dump(exclude_unset=True),
    )
    return ser.evidence_out(ev)


@router.delete("/applicants/{applicant_id}/skills/{skill_id}/evidence/{evidence_id}", status_code=204)
def delete_skill_evidence(
    applicant_id: uuid.UUID, skill_id: str, evidence_id: uuid.UUID, session: DB
) -> Response:
    _override(session, overrides.delete_evidence, applicant_id, skill_id, evidence_id)
    return Response(status_code=204)


@router.post(
    "/applicants/{applicant_id}/reverify-github",
    response_model=s.ApplicationCreated,
    status_code=202,
)
def reverify_applicant_github(
    applicant_id: uuid.UUID, session: DB, background: BackgroundTasks
) -> s.ApplicationCreated:
    """Re-collect GitHub and rerun evidence + resolve, keeping the resume profile.

    Refuses up front (409, with the reason) when it cannot work, so a manager
    never waits minutes for another "skipped".
    """
    applicant = repo.get_applicant(session, applicant_id)
    if applicant is None:
        raise not_found("Applicant")
    if applicant.status == "processing":
        raise ApiError(409, "already_processing", "This applicant is already being processed.")
    if not applicant.github_login:
        raise ApiError(409, "no_github", "This applicant did not provide a GitHub profile.")
    if latest_profile_output(applicant.id) is None:
        raise ApiError(
            409, "no_profile",
            "The resume has not been analysed successfully yet. Use Reprocess instead.",
        )
    try:
        check_github_available()
    except GitHubUnavailable as exc:
        raise ApiError(409, "github_unavailable", str(exc)) from exc
    applicant.status, applicant.status_detail = "processing", None
    session.commit()
    background.add_task(reverify_github, applicant.id)
    return s.ApplicationCreated(id=applicant.id, status="processing")


@router.get("/applicants/{applicant_id}/agent-runs/{run_id}", response_model=s.AgentRunOut)
def get_agent_run(applicant_id: uuid.UUID, run_id: uuid.UUID, session: DB) -> s.AgentRunOut:
    run = session.get(AgentRun, run_id)
    if run is None or run.applicant_id != applicant_id:
        raise not_found("Agent run")
    return ser.agent_run(run)


# ---- projects and roles ---------------------------------------------------


def _requirements(session: Session, items: list[s.RequirementIn]) -> list[ProjectRoleSkill]:
    known = repo.skill_ids(session)
    seen: set[str] = set()
    out = []
    for item in items:
        if item.skill_id not in known:
            raise ApiError(422, "unknown_skill", f"Unknown skill '{item.skill_id}'.")
        if item.skill_id in seen:
            raise ApiError(422, "duplicate_skill", f"Skill '{item.skill_id}' is listed twice.")
        seen.add(item.skill_id)
        out.append(
            ProjectRoleSkill(
                skill_id=item.skill_id,
                required_level=item.required_level,
                requirement_type=item.requirement_type,
                weight=item.weight,
            )
        )
    return out


def _commit(session: Session, conflict_message: str) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "conflict", conflict_message) from None


@router.get("/projects", response_model=list[s.ProjectOut])
def list_projects(session: DB) -> list[s.ProjectOut]:
    return [ser.project_out(p) for p in repo.list_projects(session)]


@router.get("/projects/{project_id}", response_model=s.ProjectOut)
def get_project(project_id: uuid.UUID, session: DB) -> s.ProjectOut:
    project = repo.get_project(session, project_id)
    if project is None:
        raise not_found("Project")
    return ser.project_out(project)


@router.post("/projects", response_model=s.ProjectOut, status_code=201)
def create_project(body: s.ProjectIn, session: DB) -> s.ProjectOut:
    names = [r.name.strip().lower() for r in body.roles]
    if len(names) != len(set(names)):
        raise ApiError(422, "duplicate_role", "Role names must be unique within a project.")
    project = Project(name=body.name.strip(), description=body.description, status=body.status)
    for position, role in enumerate(body.roles):
        project.roles.append(
            ProjectRole(
                name=role.name.strip(),
                description=role.description,
                capacity=role.capacity,
                position=position,
                requirements=_requirements(session, role.requirements),
            )
        )
    session.add(project)
    _commit(session, "A project with this name already exists.")
    return ser.project_out(repo.get_project(session, project.id))


@router.patch("/projects/{project_id}", response_model=s.ProjectOut)
def update_project(project_id: uuid.UUID, body: s.ProjectPatch, session: DB) -> s.ProjectOut:
    project = repo.get_project(session, project_id)
    if project is None:
        raise not_found("Project")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(project, field, value.strip() if field == "name" else value)
    _commit(session, "A project with this name already exists.")
    return ser.project_out(repo.get_project(session, project_id))


@router.post("/projects/{project_id}/roles", response_model=s.RoleOut, status_code=201)
def create_role(project_id: uuid.UUID, body: s.RoleIn, session: DB) -> s.RoleOut:
    project = repo.get_project(session, project_id)
    if project is None:
        raise not_found("Project")
    role = ProjectRole(
        project_id=project.id,
        name=body.name.strip(),
        description=body.description,
        capacity=body.capacity,
        position=len(project.roles),
        requirements=_requirements(session, body.requirements),
    )
    session.add(role)
    _commit(session, "This project already has a role with that name.")
    return ser.role_out(repo.get_role(session, role.id))


@router.patch("/roles/{role_id}", response_model=s.RoleOut)
def update_role(role_id: uuid.UUID, body: s.RolePatch, session: DB) -> s.RoleOut:
    role = repo.get_role(session, role_id)
    if role is None:
        raise not_found("Role")
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "description", "capacity"):
        if changes.get(field) is not None:
            setattr(role, field, changes[field].strip() if field == "name" else changes[field])
    if body.requirements is not None:
        role.requirements.clear()
        session.flush()
        role.requirements.extend(_requirements(session, body.requirements))
    _commit(session, "This project already has a role with that name.")
    session.expire_all()
    return ser.role_out(repo.get_role(session, role_id))


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: uuid.UUID, session: DB) -> Response:
    role = repo.get_role(session, role_id)
    if role is None:
        raise not_found("Role")
    if repo.role_in_use(session, role_id):
        raise ApiError(
            409, "role_in_use", "This role is part of assignment history and cannot be deleted."
        )
    session.delete(role)
    session.commit()
    return Response(status_code=204)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, session: DB) -> Response:
    project = repo.get_project(session, project_id)
    if project is None:
        raise not_found("Project")
    if repo.project_in_use(session, project_id):
        raise ApiError(
            409,
            "project_in_use",
            "This project is part of assignment history and cannot be deleted. Archive it instead.",
        )
    # Roles and role skills go with it via ORM cascades; assignment history is never touched.
    session.delete(project)
    session.commit()
    return Response(status_code=204)


# ---- assignment runs ------------------------------------------------------


def _run_summary(run, assigned: int) -> s.RunSummary:
    config = run.configuration or {}
    return s.RunSummary(
        id=run.id,
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        final_score=run.final_score,
        applicant_count=len(config.get("applicant_ids", [])),
        role_count=len(config.get("role_ids", [])),
        assigned_count=assigned,
        error=run.error,
    )


@router.get("/assignment-runs", response_model=list[s.RunSummary])
def list_runs(session: DB) -> list[s.RunSummary]:
    runs = repo.list_runs(session)
    counts = repo.assigned_counts(session, [r.id for r in runs])
    return [_run_summary(r, counts.get(r.id, 0)) for r in runs]


@router.post("/assignment-runs", response_model=s.RunSummary, status_code=202)
def create_run(body: s.RunCreate, session: DB, background: BackgroundTasks) -> s.RunSummary:
    try:
        run = assign.create_run(
            session, project_ids=body.project_ids, applicant_ids=body.applicant_ids, seed=body.seed
        )
    except assign.RunInputError as exc:
        raise ApiError(422, "invalid_run", str(exc)) from None
    session.commit()
    log.info("assignment run queued run=%s", run.id)
    background.add_task(assign.execute_run, run.id)
    return _run_summary(run, 0)


def _run_detail(session: Session, run_id: uuid.UUID) -> s.RunDetail:
    run = repo.get_run(session, run_id)
    if run is None:
        raise not_found("Assignment run")
    config = run.configuration or {}
    role_ids = {uuid.UUID(r) for r in config.get("role_ids", [])}
    projects = [p for p in repo.list_projects(session) if any(r.id in role_ids for r in p.roles)]
    roles = {r.id: r for p in projects for r in p.roles}
    project_by_id = {p.id: p for p in projects}
    assignments = list(repo.run_assignments(session, run.id))
    scores = list(repo.run_scores(session, run.id))
    growth = {(x.applicant_id, x.project_role_id): x.growth_score for x in scores}
    applicant_ids = [uuid.UUID(a) for a in config.get("applicant_ids", [])]
    applicants = {
        a.id: a
        for a in session.scalars(
            select(Applicant)
            .where(Applicant.id.in_(applicant_ids))
            .options(selectinload(Applicant.skills).selectinload(ApplicantSkill.skill))
        )
    }

    def ref(obj) -> s.Ref:
        return s.Ref(id=obj.id, name=obj.name)

    placed = {a.applicant_id for a in assignments if a.status != "rejected"}
    candidates: dict[uuid.UUID, int] = {}
    for x in scores:
        candidates[x.applicant_id] = candidates.get(x.applicant_id, 0) + int(x.candidate)
    active = [a for a in assignments if a.status != "rejected"]
    seats = config.get("role_seats") or {}
    before = {uuid.UUID(k): int(v) for k, v in (config.get("filled_before") or {}).items()}

    def offered(r: ProjectRole) -> int:
        return int(seats.get(str(r.id), 0 if r.id in before else r.capacity))

    # Roles filled entirely by earlier approvals were not offered, but are shown as full.
    shown = role_ids | set(before)
    projects = [p for p in repo.list_projects(session) if any(r.id in shown for r in p.roles)]
    project_by_id = {p.id: p for p in projects}
    roles = {r.id: r for p in projects for r in p.roles}
    run_roles = [r for p in projects for r in p.roles if r.id in shown]

    # Seats already taken by approved placements from other runs, as of now
    # (not the run's own filled_before snapshot, which may be stale).
    elsewhere: dict[uuid.UUID, int] = {}
    for pl in repo.approved_placements(session).values():
        if pl.assignment_run_id != run.id:
            elsewhere[pl.project_role_id] = elsewhere.get(pl.project_role_id, 0) + 1

    def open_seats(r: ProjectRole) -> int:
        taken = sum(1 for a in active if a.project_role_id == r.id)
        return max(0, min(offered(r) - taken, r.capacity - elsewhere.get(r.id, 0)))

    scores_by_applicant: dict[uuid.UUID, list] = {}
    for x in scores:
        scores_by_applicant.setdefault(x.applicant_id, []).append(x)

    def options_for(applicant_id: uuid.UUID) -> list[s.UnassignedOption]:
        return [
            s.UnassignedOption(
                role_id=x.project_role_id,
                role_name=roles[x.project_role_id].name,
                project_id=x.project_id,
                project_name=project_by_id[x.project_id].name,
                fit_score=x.fit_score,
                growth_score=x.growth_score,
                candidate=x.candidate,
                open_seats=open_seats(roles[x.project_role_id]),
            )
            for x in sorted(scores_by_applicant.get(applicant_id, []), key=lambda x: -x.fit_score)
        ]

    def skills_for(applicant: Applicant) -> list[s.SkillBadge]:
        ranked = sorted(applicant.skills, key=lambda k: (-k.final_level, k.skill.name))
        return [s.SkillBadge(skill_id=k.skill_id, name=k.skill.name, level=k.final_level) for k in ranked]
    return s.RunDetail(
        **_run_summary(run, len(active)).model_dump(),
        configuration=config,
        score_breakdown=run.score_breakdown,
        solver_details=run.solver_details,
        assignments=[
            s.AssignmentOut(
                id=a.id,
                applicant=ref(applicants[a.applicant_id]),
                project=ref(project_by_id[a.project_id]),
                role=ref(roles[a.project_role_id]),
                solver_role=ref(roles[a.solver_role_id]),
                overridden=a.project_role_id != a.solver_role_id,
                score=a.score,
                growth_score=growth.get((a.applicant_id, a.project_role_id), 0.0),
                reason=s.AssignmentReason(**a.reason),
                status=a.status,
                note=a.note,
                manual=a.manual,
                updated_at=a.updated_at,
            )
            for a in sorted(
                assignments,
                key=lambda a: (project_by_id[a.project_id].name, roles[a.project_role_id].position, -a.score),
            )
        ],
        unassigned=[
            s.UnassignedApplicant(
                id=a.id,
                name=a.name,
                candidate_role_count=candidates.get(a.id, 0),
                skills=skills_for(a),
                options=options_for(a.id),
            )
            for a in sorted(applicants.values(), key=lambda a: a.name)
            if a.id not in placed
        ]
        if run.status == "completed"
        else [],
        utilization=[
            s.ProjectUtilization(
                project_id=p.id,
                project_name=p.name,
                capacity=sum(offered(r) for r in run_roles if r.project_id == p.id),
                filled=sum(1 for a in active if a.project_id == p.id),
                filled_before=sum(before.get(r.id, 0) for r in run_roles if r.project_id == p.id),
                roles=[
                    s.RoleUtilization(
                        role_id=r.id,
                        role_name=r.name,
                        capacity=offered(r),
                        filled=sum(1 for a in active if a.project_role_id == r.id),
                        filled_before=before.get(r.id, 0),
                    )
                    for r in p.roles
                    if r.id in shown
                ],
            )
            for p in projects
        ],
    )


@router.get("/assignment-runs/{run_id}", response_model=s.RunDetail)
def get_run(run_id: uuid.UUID, session: DB) -> s.RunDetail:
    return _run_detail(session, run_id)


@router.post(
    "/assignment-runs/{run_id}/assignments", response_model=s.AssignmentOut, status_code=201
)
def create_manual_assignment(
    run_id: uuid.UUID, body: s.ManualAssignmentCreate, session: DB
) -> s.AssignmentOut:
    """A manager places an applicant into an unassigned role directly."""
    run = repo.get_run(session, run_id)
    if run is None:
        raise not_found("Assignment run")
    try:
        assignment = assign.assign_manually(session, run, body.applicant_id, body.role_id, body.note)
    except assign.RunNotCompletedError as exc:
        raise ApiError(409, "run_not_completed", str(exc)) from None
    except assign.InvalidApplicantError as exc:
        raise ApiError(422, "invalid_applicant", str(exc)) from None
    except assign.InvalidRoleError as exc:
        raise ApiError(422, "invalid_role", str(exc)) from None
    except assign.AlreadyAssignedError as exc:
        raise ApiError(409, "already_assigned", str(exc)) from None
    except assign.AlreadyPlacedError as exc:
        raise ApiError(409, "already_placed", str(exc)) from None
    except assign.RoleFullError as exc:
        raise ApiError(409, "role_full", str(exc)) from None
    session.commit()
    detail = _run_detail(session, run_id)
    return next(a for a in detail.assignments if a.id == assignment.id)


@router.patch("/assignments/{assignment_id}", response_model=s.AssignmentOut)
def update_assignment(assignment_id: uuid.UUID, body: s.AssignmentPatch, session: DB) -> s.AssignmentOut:
    assignment = session.get(Assignment, assignment_id)
    if assignment is None:
        raise not_found("Assignment")
    try:
        if body.role_id is not None:
            assign.override_role(session, assignment, body.role_id)
    except assign.RoleFullError as exc:
        raise ApiError(409, "role_full", str(exc)) from None
    except assign.RunInputError as exc:
        raise ApiError(422, "invalid_role", str(exc)) from None
    if body.status == "approved" and assignment.status != "approved":
        try:
            assign.check_approval(session, assignment)
        except assign.AlreadyPlacedError as exc:
            raise ApiError(409, "already_placed", str(exc)) from None
        except assign.RoleFullError as exc:
            raise ApiError(409, "role_full", str(exc)) from None
    if body.status is not None:
        assignment.status = body.status
    if body.note is not None:
        assignment.note = body.note
    session.commit()
    detail = _run_detail(session, assignment.assignment_run_id)
    return next(a for a in detail.assignments if a.id == assignment_id)
