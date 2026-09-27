"""Assignment runs: DB state -> existing scoring + optimizer -> persisted results.

The matching engine (src/matching) assigns students to "projects" with a team
size range and flat skill requirements; it has no notion of roles. Each
project role is therefore handed to it as one matching unit:

    matching project_id  = role id
    max_team_size        = role capacity
    requirements         = the role's skill requirements

so capacity is enforced per role, scores are applicant x role, and the
optimizer itself is unchanged. It is a global optimization (genetic
algorithm), not a greedy one-by-one assignment.

Approved placements are commitments: a new run leaves out applicants who
already have one and offers each role only its remaining seats.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend import repositories as repo
from backend.db import session_scope
from backend.db.models import (
    Applicant,
    ApplicantRoleScore,
    Assignment,
    AssignmentRun,
    Project,
    ProjectRole,
)
from matching import optimize_matching
from matching.preprocessing import preprocess_inputs
from matching.pruning import build_candidate_options
from matching.schemas import (
    GAConfig,
    MatchingInput,
    ProjectProfile,
    ProjectSkillRequirement,
    StudentProfile,
    StudentSkill,
    TaxonomyTree,
)
from matching.scoring import student_growth_opportunity_score, student_project_fit

log = logging.getLogger(__name__)

SOLVER_VERSION = "matching-ga/1"
# Bump when the pairwise score or reason composition changes.
SCORING_VERSION = "role-fit/1"
LEVEL = {1: "Entry", 2: "Intermediate", 3: "Advanced"}


class RunInputError(ValueError):
    """The run cannot start: nothing to assign or nothing to assign to."""


def create_run(
    session: Session,
    *,
    project_ids: list[uuid.UUID] | None,
    applicant_ids: list[uuid.UUID] | None,
    seed: int,
) -> AssignmentRun:
    """Validate inputs and record a queued run. The optimizer runs later."""
    projects = [
        p
        for p in repo.list_projects(session, status=None if project_ids else "active")
        if project_ids is None or p.id in set(project_ids)
    ]
    placed = repo.approved_placements(session)
    filled = repo.filled_seats(placed)
    all_roles = [r for p in projects for r in p.roles if r.requirements]
    if not all_roles:
        raise RunInputError("No project roles with skill requirements to assign to.")
    seats = {r.id: r.capacity - filled.get(r.id, 0) for r in all_roles}
    roles = [r for r in all_roles if seats[r.id] > 0]
    ready = repo.ready_applicants(session, applicant_ids)
    applicants = [a for a in ready if a.id not in placed]
    if not roles:
        raise RunInputError("Every role is already filled by approved placements.")
    if not applicants:
        raise RunInputError(
            "No applicants left to assign: every 'ready' applicant already has an approved placement."
            if ready
            else "No applicants with status 'ready' to assign."
        )
    run = AssignmentRun(
        status="queued",
        configuration={
            "project_ids": [str(p.id) for p in projects],
            "role_ids": [str(r.id) for r in roles],
            # Seats left after approved placements; the optimizer's team size.
            "role_seats": {str(r.id): seats[r.id] for r in roles},
            # Approved placements from earlier runs, per role (full roles included).
            "filled_before": {
                str(r.id): filled[r.id] for r in all_roles if filled.get(r.id)
            },
            "excluded_placed_applicants": len(ready) - len(applicants),
            "applicant_ids": [str(a.id) for a in applicants],
            "ga": GAConfig(seed=seed).model_dump(),
            "unit": "project_role",
        },
        solver_version=SOLVER_VERSION,
        scoring_version=SCORING_VERSION,
    )
    session.add(run)
    session.flush()
    return run


def _matching_input(
    applicants: list[Applicant],
    roles: list[ProjectRole],
    skills: list[tuple[str, str]],
    ga: dict,
    seats: dict[str, int] | None = None,
) -> MatchingInput:
    return MatchingInput(
        students=[
            StudentProfile(
                student_id=str(a.id),
                name=a.reference,
                skills=[StudentSkill(skill_id=s.skill_id, level=s.final_level) for s in a.skills],
            )
            for a in applicants
        ],
        projects=[
            ProjectProfile(
                project_id=str(r.id),
                name=f"{r.project.name} / {r.name}",
                min_team_size=1,
                max_team_size=(seats or {}).get(str(r.id), r.capacity),
                requirements=[
                    ProjectSkillRequirement(
                        skill_id=q.skill_id,
                        required_level=q.required_level,
                        requirement_type=q.requirement_type,
                        importance=q.weight,
                    )
                    for q in r.requirements
                ],
            )
            for r in roles
        ],
        # Flat taxonomy: only exact skill ids match, as in pipeline/integrated.py.
        # Sharing a category (e.g. Language) does not make Java and Python equivalent.
        taxonomy=TaxonomyTree(nodes=[{"skill_id": sid, "name": name} for sid, name in skills]),
        config=GAConfig(**ga),
    )


def explain(levels: dict[str, int], role: ProjectRole, names: dict[str, str]) -> dict[str, Any]:
    """Deterministic, user-facing reason for placing an applicant in a role."""
    met, below, growth = [], [], []
    for q in role.requirements:
        name = names.get(q.skill_id, q.skill_id)
        have = levels.get(q.skill_id)
        if q.requirement_type == "learning_opportunity":
            if have is None or have < q.required_level:
                start = LEVEL.get(have, "new") if have else "new"
                growth.append(f"{name}: {start} -> {LEVEL[q.required_level]}")
            else:
                met.append(f"{name} ({LEVEL[have]})")
        elif have is not None and have >= q.required_level:
            met.append(f"{name} ({LEVEL[have]})")
        else:
            label = "Required" if q.requirement_type == "hard_requirement" else "Preferred"
            below.append(
                f"{name}: {LEVEL.get(have, 'none') if have else 'none'} of "
                f"{LEVEL[q.required_level]} ({label.lower()})"
            )
    parts = []
    if met:
        parts.append(f"meets {len(met)} requirement(s)")
    if growth:
        parts.append(f"{len(growth)} growth skill(s)")
    if below:
        parts.append(f"{len(below)} below target")
    return {
        "met": met,
        "below": below,
        "growth": growth,
        "summary": (", ".join(parts) or "no overlapping skills").capitalize() + ".",
    }


def execute_run(run_id: uuid.UUID) -> None:
    """Score every applicant x role, optimize, and persist. Safe in a background task."""
    with session_scope() as session:
        run = session.get(AssignmentRun, run_id)
        if run is None or run.status != "queued":
            return
        run.status, run.started_at = "running", datetime.now(UTC)
    log.info("assignment run started run=%s", run_id)
    try:
        with session_scope() as session:
            _execute(session, run_id)
        log.info("assignment run completed run=%s", run_id)
    except Exception as exc:
        log.exception("assignment run failed run=%s", run_id)
        with session_scope() as session:
            run = session.get(AssignmentRun, run_id)
            run.status, run.completed_at = "failed", datetime.now(UTC)
            run.error = f"The optimizer could not complete this run ({type(exc).__name__})."


def _execute(session: Session, run_id: uuid.UUID) -> None:
    run = session.get(AssignmentRun, run_id)
    config = run.configuration
    role_ids = {uuid.UUID(r) for r in config["role_ids"]}
    applicant_ids = [uuid.UUID(a) for a in config["applicant_ids"]]

    roles = [
        r
        for p in repo.list_projects(session)
        for r in p.roles
        if r.id in role_ids and r.requirements
    ]
    applicants = list(repo.ready_applicants(session, applicant_ids))
    if not roles or not applicants:
        raise RunInputError("Run inputs changed since the run was queued.")
    skills = [(s.id, s.name) for s in repo.list_skills(session)]
    names = dict(skills)

    data = _matching_input(applicants, roles, skills, config["ga"], config.get("role_seats"))
    context = preprocess_inputs(data)
    options = build_candidate_options(context)
    students = {s.student_id: s for s in data.students}
    units = {p.project_id: p for p in data.projects}
    role_by_id = {str(r.id): r for r in roles}

    pair: dict[tuple[str, str], tuple[float, float]] = {}
    for sid, student in students.items():
        for pid, unit in units.items():
            fit = student_project_fit(student, unit, context)
            growth_reqs = [
                q for q in unit.requirements if q.requirement_type.value == "learning_opportunity"
            ]
            growth = (
                sum(student_growth_opportunity_score(student, q, context) * q.importance for q in growth_reqs)
                / sum(q.importance for q in growth_reqs)
                if growth_reqs
                else 0.0
            )
            pair[(sid, pid)] = (fit, growth)
            session.add(
                ApplicantRoleScore(
                    assignment_run_id=run_id,
                    applicant_id=uuid.UUID(sid),
                    project_id=role_by_id[pid].project_id,
                    project_role_id=uuid.UUID(pid),
                    candidate=pid in options[sid],
                    fit_score=round(fit, 2),
                    growth_score=round(growth, 2),
                    breakdown={
                        q.skill_id: {
                            "required_level": q.required_level,
                            "type": q.requirement_type.value,
                            "growth": round(student_growth_opportunity_score(student, q, context), 2),
                        }
                        for q in unit.requirements
                    },
                )
            )

    result = optimize_matching(data)

    levels_by_applicant = {
        str(a.id): {s.skill_id: s.final_level for s in a.skills} for a in applicants
    }
    for sid, pid in result.assignments.items():
        if pid is None:
            continue
        role = role_by_id[pid]
        fit, _ = pair[(sid, pid)]
        session.add(
            Assignment(
                assignment_run_id=run_id,
                applicant_id=uuid.UUID(sid),
                project_id=role.project_id,
                project_role_id=role.id,
                solver_role_id=role.id,
                score=round(fit, 2),
                reason=explain(levels_by_applicant[sid], role, names),
                status="proposed",
            )
        )

    run.status, run.completed_at = "completed", datetime.now(UTC)
    run.final_score = round(result.final_score, 2)
    run.score_breakdown = {k: round(v, 2) for k, v in result.score_breakdown.items()}
    run.solver_details = {
        "generations": result.generations,
        "stop_reason": result.stop_reason,
        "unassigned_role_ids": result.unassigned_projects,
    }


def override_role(session: Session, assignment: Assignment, role_id: uuid.UUID) -> None:
    """Move an assignment to another role in the same run, respecting capacity."""
    run = session.get(AssignmentRun, assignment.assignment_run_id)
    if str(role_id) not in run.configuration.get("role_ids", []):
        raise RunInputError("That role was not part of this assignment run.")
    role = session.get(ProjectRole, role_id)
    if role is None:
        raise RunInputError("Unknown role.")
    if role_id != assignment.project_role_id:
        in_run = [
            a for a in repo.run_assignments(session, run.id)
            if a.project_role_id == role_id and a.status != "rejected"
        ]
        elsewhere = [
            a for a in repo.approved_placements(session).values()
            if a.project_role_id == role_id and a.assignment_run_id != run.id
        ]
        if len(in_run) + len(elsewhere) >= role.capacity:
            raise RoleFullError(f"{role.name} is already at capacity ({role.capacity}).")
    assignment.project_role_id = role.id
    assignment.project_id = role.project_id
    applicant = session.get(Applicant, assignment.applicant_id)
    names = {s.id: s.name for s in repo.list_skills(session)}
    assignment.reason = explain({s.skill_id: s.final_level for s in applicant.skills}, role, names)
    score = next(
        (
            s.fit_score
            for s in repo.run_scores(session, run.id)
            if s.applicant_id == assignment.applicant_id and s.project_role_id == role_id
        ),
        assignment.score,
    )
    assignment.score = score


class RoleFullError(RunInputError):
    """The target role has no free capacity."""


class AlreadyPlacedError(RunInputError):
    """The applicant already has an approved placement from another run."""


def check_approval(session: Session, assignment: Assignment) -> None:
    """Approving commits a seat: one approved placement per applicant, and
    approved placements never exceed a role's capacity across runs."""
    placed = repo.approved_placements(session, exclude_assignment=assignment.id)
    existing = placed.get(assignment.applicant_id)
    if existing is not None:
        role = session.get(ProjectRole, existing.project_role_id)
        raise AlreadyPlacedError(
            f"This applicant is already placed in {role.project.name} / {role.name}. "
            "Reject that placement first."
        )
    role = session.get(ProjectRole, assignment.project_role_id)
    if repo.filled_seats(placed).get(role.id, 0) >= role.capacity:
        raise RoleFullError(
            f"{role.project.name} / {role.name} is already full "
            f"({role.capacity} approved placement(s))."
        )


def project_capacity(project: Project) -> int:
    return sum(r.capacity for r in project.roles)
