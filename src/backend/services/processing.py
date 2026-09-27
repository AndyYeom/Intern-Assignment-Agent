"""Run the existing agent pipeline for one applicant and persist the result.

Stages (each recorded as an AgentRun):
  profile   resume PDF -> ApplicantProfile        (profile agent, LLM)
  github    GitHub login -> collected profile     (generator.github collector)
  evidence  claims vs GitHub -> EvidenceReport    (evidence agent, rules + LLM)
  resolve   claimed vs observed -> final levels   (pipeline/resolve_profile.py)

Each run keeps its structured output (and the error, if any) so a manager can
see what every agent produced. `reverify_github` reruns only the last three
stages on the stored profile, e.g. after the GitHub quota was exhausted.

No database transaction is held open across a model call. Runs in the API
process after the request returns; a crash leaves the applicant "processing"
and a manager can reprocess it.
"""

import logging
import os
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.config import get_settings
from backend.db import session_scope
from backend.db.models import AgentRun, Applicant
from backend.services.persistence import replace_applicant_skills
from backend.services.skill_resolution import resolve_skills
from backend.storage import LocalStorage

log = logging.getLogger(__name__)

# Shown to applicants; never contains internals.
FAILURE_MESSAGE = "We could not process your resume automatically. Our team will review it."

# GitHub requests one applicant usually needs (observed 36-55).
GITHUB_REQUESTS_PER_APPLICANT = 55


class GitHubUnavailable(RuntimeError):
    """GitHub cannot be used right now; the message says why, for managers."""


def github_quota() -> dict[str, Any]:
    """Current GitHub core quota for the key this process would use.

    /rate_limit itself does not count against the quota. A rejected token is
    reported and the anonymous quota (the collector's fallback) is returned.
    """
    from generator.config import API_ROOT, USER_AGENT, github_token

    def fetch(token: str | None) -> httpx.Response:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.get(f"{API_ROOT}/rate_limit", headers=headers, timeout=10)

    token = github_token()
    token_rejected = False
    try:
        response = fetch(token)
        if response.status_code == 401 and token:
            token_rejected, token = True, None
            response = fetch(None)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise GitHubUnavailable(f"Could not reach the GitHub API ({type(exc).__name__}).") from exc
    core = response.json()["resources"]["core"]
    return {
        "authenticated": bool(token),
        "token_rejected": token_rejected,
        "limit": core["limit"],
        "remaining": core["remaining"],
        "reset_at": datetime.fromtimestamp(core["reset"], UTC),
    }


def check_github_available() -> dict[str, Any]:
    """Raise GitHubUnavailable (with a readable reason) unless one applicant fits the quota."""
    quota = github_quota()
    if quota["remaining"] >= GITHUB_REQUESTS_PER_APPLICANT:
        return quota
    minutes = max(1, round((quota["reset_at"].timestamp() - time.time()) / 60))
    key = "the GITHUB_TOKEN" if quota["authenticated"] else "anonymous access (no GITHUB_TOKEN)"
    reason = (
        f"GitHub quota for {key} is nearly used up: {quota['remaining']} of "
        f"{quota['limit']} requests left, one applicant needs about "
        f"{GITHUB_REQUESTS_PER_APPLICANT}. It resets in about {minutes} min "
        f"({quota['reset_at']:%H:%M} UTC)."
    )
    if quota["token_rejected"]:
        reason += " GITHUB_TOKEN was rejected by GitHub (expired or revoked); set a valid token and restart the backend."
    elif not quota["authenticated"]:
        reason += " Set GITHUB_TOKEN (5,000 requests/hour) and restart the backend."
    raise GitHubUnavailable(reason)


def _github_failure(exc: Exception, login: str) -> str:
    from generator.github.client import NotFound, RateLimited

    if isinstance(exc, RateLimited):
        return "GitHub rate limit reached; use \"Rerun GitHub verification\" after it resets."
    if isinstance(exc, NotFound):
        return f"GitHub user '{login}' was not found."
    if isinstance(exc, httpx.HTTPStatusError):
        return f"GitHub returned HTTP {exc.response.status_code}."
    return f"GitHub collection failed: {type(exc).__name__}"


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


def _ensure_github_profile(applicant: dict[str, Any], *, refresh: bool = False) -> tuple[Any | None, str]:
    """Get this applicant's GitHubProfile without ever writing a file.

    Reuses the DB snapshot when present (also preserves the anonymous 60
    requests/hour quota on reprocessing). Otherwise collects in memory - no
    raw bundle under legacy/githubs/, no on-disk HTTP cache - and stores the
    built profile straight into applicants.github_snapshot.

    Returns (GitHubProfile | None, note).
    """
    from generator.github.normalize import build_profile
    from generator.schemas import GitHubProfile

    if applicant["github_snapshot"] and not refresh:
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


def _load(applicant_id: uuid.UUID) -> dict[str, Any] | None:
    """Mark the applicant processing and return what the stages need."""
    with session_scope() as session:
        applicant = session.get(Applicant, applicant_id)
        if applicant is None:
            log.warning("unknown applicant id=%s", applicant_id)
            return None
        resume = next((d for d in applicant.documents if d.document_type == "resume"), None)
        applicant.status, applicant.status_detail = "processing", None
        return {
            "id": applicant.id,
            "reference": applicant.reference,
            "github_login": applicant.github_login,
            "github_snapshot": applicant.github_snapshot,
            "resume_key": resume.storage_key if resume else None,
        }


def _fail(applicant_id: uuid.UUID) -> None:
    with session_scope() as session:
        applicant = session.get(Applicant, applicant_id)
        applicant.status, applicant.status_detail = "failed", FAILURE_MESSAGE


def latest_profile_output(applicant_id: uuid.UUID) -> dict[str, Any] | None:
    """The newest successful profile agent output, if any."""
    from sqlalchemy import select

    with session_scope() as session:
        return session.scalars(
            select(AgentRun.output)
            .where(AgentRun.applicant_id == applicant_id, AgentRun.agent_type == "profile",
                   AgentRun.status == "succeeded", AgentRun.output.is_not(None))
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        ).first()


def process_applicant(applicant_id: uuid.UUID) -> None:
    """Profile, verify and resolve one applicant. Safe to call again to reprocess."""
    from src.profile_agent.profile_graph import evaluate_resume

    snapshot = _load(applicant_id)
    if snapshot is None:
        return
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
        _fail(applicant_id)
        return

    _verify_and_resolve(snapshot, profile, model)


def reverify_github(applicant_id: uuid.UUID) -> None:
    """Re-collect GitHub and rerun evidence + resolve on the stored profile (no resume LLM call)."""
    from src.profile_agent.profile_models import ApplicantProfile

    output = latest_profile_output(applicant_id)
    snapshot = _load(applicant_id)
    if snapshot is None:
        return
    if output is None:
        log.warning("reverify_github: no profile output applicant=%s", snapshot["reference"])
        _fail(applicant_id)
        return
    log.info("GitHub re-verification started applicant=%s", snapshot["reference"])
    _verify_and_resolve(snapshot, ApplicantProfile.model_validate(output), _gateway_model(),
                        refresh_github=True)


def _verify_and_resolve(snapshot: dict[str, Any], profile: Any, model: str | None,
                        *, refresh_github: bool = False) -> None:
    from src.evidence_agent import evaluate_github

    applicant_id, ref = snapshot["id"], snapshot["reference"]
    verifications: list[dict[str, Any]] = []
    github_profile = None
    with _Stage(applicant_id, "github") as stage:
        try:
            github_profile, note = _ensure_github_profile(snapshot, refresh=refresh_github)
        except Exception as exc:  # GitHub down, bad login, rate limit: continue unverified
            github_profile, note = None, _github_failure(exc, snapshot["github_login"])
            stage.error = f"{type(exc).__name__}: {exc}"[:2000]
            log.warning("github stage failed applicant=%s: %s", ref, exc)
        stage.status = "succeeded" if github_profile is not None else "skipped"
        stage.details = {"note": note, "repos": len(github_profile.repos) if github_profile else 0}
        if github_profile is not None:
            stage.output = github_profile.model_dump(mode="json")

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
            stage.output = {"skills": [asdict(k) for k in skills], "unmapped": unmapped}
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
        _fail(applicant_id)
        return
    log.info("processing finished applicant=%s skills=%d", ref, len(skills))
