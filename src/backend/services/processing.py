"""Run the existing agent pipeline for one applicant and persist the result.

Stages (each recorded as an AgentRun):
  profile   resume PDF -> ApplicantProfile        (profile agent, LLM)
  github    GitHub login -> collected profile     (generator.github collector)
  evidence  claims vs GitHub -> EvidenceReport    (evidence agent, rules + LLM)
  resolve   claimed vs observed -> final levels   (pipeline/resolve_profile.py)

No database transaction is held open across a model call. Runs in the API
process after the request returns; a crash leaves the applicant "processing"
and a manager can reprocess it.
"""

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.config import get_settings
from backend.db import session_scope
from backend.db.models import AgentRun, Applicant
from backend.services.persistence import replace_applicant_skills
from backend.services.skill_resolution import resolve_skills
from backend.storage import LocalStorage

log = logging.getLogger(__name__)

# Shown to applicants; never contains internals.
FAILURE_MESSAGE = "We could not process your resume automatically. Our team will review it."


class _Stage:
    """Context manager that records one AgentRun and never leaks details upward."""

    def __init__(self, applicant_id: uuid.UUID, agent_type: str, model: str | None = None):
        self.applicant_id, self.agent_type, self.model = applicant_id, agent_type, model
        self.status, self.output, self.details, self.error = "succeeded", None, None, None

    def __enter__(self) -> "_Stage":
        with session_scope() as session:
            run = AgentRun(
                applicant_id=self.applicant_id,
                agent_type=self.agent_type,
                status="running",
                model=self.model,
            )
            session.add(run)
            session.flush()
            self.run_id = run.id
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.status = "failed"
            self.error = f"{type(exc).__name__}: {exc}"[:2000]
        with session_scope() as session:
            run = session.get(AgentRun, self.run_id)
            run.status, run.output, run.details = self.status, self.output, self.details
            run.error, run.completed_at = self.error, datetime.now(UTC)
        return False


def _gateway_model() -> str | None:
    from project_catalog_agent.llm import gateway_configured

    return os.environ.get("LLM_MODEL") if gateway_configured() else None


def _ensure_github_profile(applicant: dict[str, Any]) -> tuple[Any | None, str]:
    """Get this applicant's GitHubProfile without ever writing a file.

    Reuses the DB snapshot when present (also preserves the anonymous 60
    requests/hour quota on reprocessing). Otherwise collects in memory - no
    raw bundle under legacy/githubs/, no on-disk HTTP cache - and stores the
    built profile straight into applicants.github_snapshot.

    Returns (GitHubProfile | None, note).
    """
    from generator.github.normalize import build_profile
    from generator.schemas import GitHubProfile

    if applicant["github_snapshot"]:
        return GitHubProfile.model_validate(applicant["github_snapshot"]), "using stored GitHub snapshot"
    if not applicant["github_login"]:
        return None, "no GitHub login provided"

    import httpx
    from generator.github.cache import InMemoryResponseCache
    from generator.github.client import GitHubClient
    from generator.github.collector import collect_user

    def _collect(token: str | None) -> tuple[dict[str, Any], GitHubClient]:
        client = GitHubClient(token=token, cache=InMemoryResponseCache(), wait_on_limit=False)
        return collect_user(client, applicant["github_login"], persist=False), client

    try:
        bundle, client = _collect(None)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise
        # A rejected GITHUB_TOKEN: public data is still readable anonymously
        # (60 requests/hour, roughly one applicant).
        log.warning("GITHUB_TOKEN rejected (401); collecting anonymously")
        bundle, client = _collect("")
    profile = build_profile(bundle, applicant["reference"])
    with session_scope() as session:
        session.get(Applicant, applicant["id"]).github_snapshot = profile.model_dump(mode="json")
    note = f"collected {len(profile.repos)} repositories"
    if client.request_count:
        note += f", {client.request_count} GitHub requests"
    return profile, note


def process_applicant(applicant_id: uuid.UUID) -> None:
    """Profile, verify and resolve one applicant. Safe to call again to reprocess."""
    from src.evidence_agent import evaluate_github
    from src.profile_agent.profile_graph import evaluate_resume

    with session_scope() as session:
        applicant = session.get(Applicant, applicant_id)
        if applicant is None:
            log.warning("process_applicant: unknown applicant id=%s", applicant_id)
            return
        resume = next((d for d in applicant.documents if d.document_type == "resume"), None)
        applicant.status, applicant.status_detail = "processing", None
        snapshot = {
            "id": applicant.id,
            "reference": applicant.reference,
            "github_login": applicant.github_login,
            "github_snapshot": applicant.github_snapshot,
            "resume_key": resume.storage_key if resume else None,
        }
    ref = snapshot["reference"]
    log.info("processing started applicant=%s", ref)
    model = _gateway_model()

    try:
        if snapshot["resume_key"] is None:
            raise ValueError("no resume on file")
        storage = LocalStorage(get_settings().storage_root)
        with _Stage(applicant_id, "profile", model) as stage:
            with storage.as_local_file(snapshot["resume_key"]) as resume_path:
                profile = evaluate_resume(resume_path, applicant_id=ref)
            stage.output = profile.model_dump(mode="json")
            stage.details = {"skills": len(profile.skills)}
    except Exception:
        log.exception("profile stage failed applicant=%s", ref)
        with session_scope() as session:
            applicant = session.get(Applicant, applicant_id)
            applicant.status, applicant.status_detail = "failed", FAILURE_MESSAGE
        return

    verifications: list[dict[str, Any]] = []
    github_profile = None
    with _Stage(applicant_id, "github") as stage:
        try:
            github_profile, note = _ensure_github_profile(snapshot)
        except Exception as exc:  # GitHub down, bad login, rate limit: continue unverified
            github_profile, note = None, f"GitHub collection failed: {type(exc).__name__}"
            log.warning("github stage failed applicant=%s: %s", ref, exc)
        stage.status = "succeeded" if github_profile is not None else "skipped"
        stage.details = {"note": note, "repos": len(github_profile.repos) if github_profile else 0}

    if github_profile is not None:
        with _Stage(applicant_id, "evidence", model) as stage:
            try:
                report = evaluate_github(ref, profile, use_llm=model is not None,
                                         github=github_profile)
                verifications = [s.model_dump(mode="json") for s in report.skills]
                stage.output = report.payload()
                stage.details = {"mode": report.mode, "status_counts": report.status_counts}
            except Exception as exc:
                stage.status, stage.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
                log.warning("evidence stage failed applicant=%s: %s", ref, exc)
    else:
        with _Stage(applicant_id, "evidence") as stage:
            stage.status = "skipped"
            stage.details = {"note": "no GitHub data; claims stay unverified"}

    try:
        with _Stage(applicant_id, "resolve") as stage:
            claims = [s.model_dump(mode="json") for s in profile.skills]
            skills, unmapped = resolve_skills(claims, verifications)
            stage.details = {"skills": len(skills), "unmapped": unmapped}
            with session_scope() as session:
                applicant = session.get(Applicant, applicant_id)
                replace_applicant_skills(session, applicant, skills)
                applicant.profile = {
                    "domains": profile.domains,
                    "interests": profile.interests,
                    "education": [e.model_dump(mode="json") for e in profile.education],
                    "work_experience": [
                        w.model_dump(mode="json") for w in profile.work_experience
                    ],
                    "unmapped_skills": unmapped,
                }
                applicant.status = "ready"
                applicant.processed_at = datetime.now(UTC)
    except Exception:
        log.exception("resolve stage failed applicant=%s", ref)
        with session_scope() as session:
            applicant = session.get(Applicant, applicant_id)
            applicant.status, applicant.status_detail = "failed", FAILURE_MESSAGE
        return
    log.info("processing finished applicant=%s skills=%d", ref, len(skills))
