"""Database rows -> API response models."""

from backend.api import schemas as s
from backend.db.models import (
    AgentRun,
    Applicant,
    ApplicantRoleScore,
    ApplicantSkill,
    ApplicantSkillEvidence,
    Assignment,
    Project,
    ProjectRole,
)

STAGE_MESSAGES = {
    ("profile", "failed"): "Resume could not be analysed.",
    ("github", "skipped"): "GitHub data unavailable; skills are unverified.",
    ("evidence", "skipped"): "GitHub verification skipped.",
    ("evidence", "failed"): "GitHub verification failed; skills are unverified.",
    ("resolve", "failed"): "Skills could not be finalised.",
}


def top_skills(applicant: Applicant, limit: int = 3) -> list[s.SkillBadge]:
    ranked = sorted(applicant.skills, key=lambda k: (-k.final_level, k.skill.name))
    return [
        s.SkillBadge(skill_id=k.skill_id, name=k.skill.name, level=k.final_level)
        for k in ranked[:limit]
    ]


def assignment_summary(a: Assignment | None, names: dict) -> s.AssignmentSummary | None:
    if a is None:
        return None
    return s.AssignmentSummary(
        assignment_id=a.id,
        run_id=a.assignment_run_id,
        project_id=a.project_id,
        project_name=names["projects"].get(a.project_id, "?"),
        role_id=a.project_role_id,
        role_name=names["roles"].get(a.project_role_id, "?"),
        status=a.status,
        score=a.score,
    )


def applicant_item(a: Applicant, assignment: Assignment | None, names: dict) -> s.ApplicantListItem:
    return s.ApplicantListItem(
        id=a.id,
        reference=a.reference,
        name=a.name,
        email=a.email,
        github_url=a.github_url,
        status=a.status,
        source=a.source,
        submitted_at=a.created_at,
        skill_count=len(a.skills),
        top_skills=top_skills(a),
        assignment=assignment_summary(assignment, names),
    )


def stage(run: AgentRun) -> s.ProcessingStage:
    note = (run.details or {}).get("note")
    return s.ProcessingStage(
        run_id=run.id,
        agent_type=run.agent_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        message=note or STAGE_MESSAGES.get((run.agent_type, run.status)),
        model=run.model,
        details=run.details,
        error=run.error,
        has_output=run.output is not None,
    )


def agent_run(run: AgentRun) -> s.AgentRunOut:
    return s.AgentRunOut(**stage(run).model_dump(), output=run.output)


def latest_attempt(runs: list[AgentRun]) -> list[AgentRun]:
    """The newest run of each stage in the latest attempt.

    An attempt starts with a profile run (full reprocess) or a github run
    (GitHub re-verification, which keeps the earlier profile run); stages
    older than the attempt's start are left out.
    """
    latest: dict[str, AgentRun] = {}
    for run in sorted(runs, key=lambda r: r.started_at):
        latest[run.agent_type] = run
    profile, github = latest.get("profile"), latest.get("github")
    start = github.started_at if github else (profile.started_at if profile else None)
    order = ("profile", "github", "evidence", "resolve")
    return [
        latest[t] for t in order
        if t in latest and (t == "profile" or start is None or latest[t].started_at >= start)
    ]


def evidence_out(e: ApplicantSkillEvidence) -> s.EvidenceOut:
    return s.EvidenceOut(
        id=e.id,
        source_type=e.source_type,
        reference=e.reference,
        excerpt=e.excerpt,
        level=e.level,
        edited_at=e.edited_at,
    )


def skill_out(k: ApplicantSkill) -> s.ApplicantSkillOut:
    return s.ApplicantSkillOut(
        skill_id=k.skill_id,
        name=k.skill.name,
        category=k.skill.category,
        final_level=k.final_level,
        claimed_level=k.claimed_level,
        observed_level=k.observed_level,
        verification_status=k.verification_status,
        evidence_strength=k.evidence_strength,
        flag=k.flag,
        confidence=k.confidence,
        claim_summary=k.claim_summary,
        verification_summary=k.verification_summary,
        evidence=[evidence_out(e) for e in k.evidence],
        source=k.source,
        edited_at=k.edited_at,
    )


def applicant_detail(
    a: Applicant,
    assignment: Assignment | None,
    runs: list[AgentRun],
    scores: list[ApplicantRoleScore],
    names: dict,
) -> s.ApplicantDetail:
    item = applicant_item(a, assignment, names)
    return s.ApplicantDetail(
        **item.model_dump(),
        portfolio_url=a.portfolio_url,
        github_login=a.github_login,
        status_detail=a.status_detail,
        processed_at=a.processed_at,
        profile=a.profile,
        documents=[
            s.DocumentOut(
                id=d.id,
                document_type=d.document_type,
                original_filename=d.original_filename,
                mime_type=d.mime_type,
                size_bytes=d.size_bytes,
                download_path=f"/api/manager/applicants/{a.id}/documents/{d.id}",
            )
            for d in a.documents
        ],
        skills=[skill_out(k) for k in sorted(a.skills, key=lambda k: (-k.final_level, k.skill.name))],
        stages=[stage(r) for r in latest_attempt(runs)],
        scores=[
            s.RoleScoreOut(
                run_id=x.assignment_run_id,
                project_id=x.project_id,
                project_name=names["projects"].get(x.project_id, "?"),
                role_id=x.project_role_id,
                role_name=names["roles"].get(x.project_role_id, "?"),
                candidate=x.candidate,
                fit_score=x.fit_score,
                growth_score=x.growth_score,
            )
            for x in scores[:10]
        ],
    )


def role_out(role: ProjectRole) -> s.RoleOut:
    return s.RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        capacity=role.capacity,
        requirements=[
            s.RequirementOut(
                skill_id=q.skill_id,
                skill_name=q.skill.name,
                required_level=q.required_level,
                requirement_type=q.requirement_type,
                weight=q.weight,
            )
            for q in role.requirements
        ],
    )


def project_out(p: Project) -> s.ProjectOut:
    return s.ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        status=p.status,
        capacity=sum(r.capacity for r in p.roles),
        roles=[role_out(r) for r in p.roles],
        created_at=p.created_at,
        updated_at=p.updated_at,
    )
