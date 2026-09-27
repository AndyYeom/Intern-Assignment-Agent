"""Database rows -> API response models."""

from backend.api import schemas as s
from backend.db.models import (
    AgentRun,
    Applicant,
    ApplicantRoleScore,
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
        agent_type=run.agent_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        message=STAGE_MESSAGES.get((run.agent_type, run.status), note if run.status != "failed" else None),
    )


def applicant_detail(
    a: Applicant,
    assignment: Assignment | None,
    runs: list[AgentRun],
    scores: list[ApplicantRoleScore],
    names: dict,
) -> s.ApplicantDetail:
    item = applicant_item(a, assignment, names)
    # Only the most recent processing attempt, which starts with a profile run.
    starts = [r.started_at for r in runs if r.agent_type == "profile"]
    attempt = [r for r in runs if not starts or r.started_at >= max(starts)]
    latest: dict[str, AgentRun] = {}
    for run in attempt:
        latest[run.agent_type] = run
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
        skills=[
            s.ApplicantSkillOut(
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
                evidence=[
                    s.EvidenceOut(
                        source_type=e.source_type, reference=e.reference, excerpt=e.excerpt, level=e.level
                    )
                    for e in k.evidence
                ],
            )
            for k in sorted(a.skills, key=lambda k: (-k.final_level, k.skill.name))
        ],
        stages=[stage(r) for r in latest.values()],
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
