"""process_applicant end to end: GitHub scraping, evidence and profile results all
land in Postgres, and nothing is ever written to legacy/githubs/ or the HTTP cache.

The network and the LLM gateway are stubbed; the evidence agent's rules engine
runs for real (use_llm=False, since no gateway is configured in tests).
"""

from __future__ import annotations

import uuid

import pytest
from generator.schemas import GitHubProfile, RepoRecord
from tests.test_evidence import _profile, _repo

from backend.config import get_settings
from backend.db import session_scope
from backend.db.models import Applicant, ApplicantDocument, ApplicantSkill
from backend.storage import LocalStorage

PDF = b"%PDF-1.4\n% test resume\n"


@pytest.fixture(autouse=True)
def no_llm_gateway(monkeypatch):
    """Force the "no gateway configured" path: evidence runs rules-only, never
    calling out to a real LLM gateway."""
    for name in ("LLM_GATEWAY_URL", "LLM_GATEWAY_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _make_applicant(reference: str, github_login: str | None = "octocat") -> uuid.UUID:
    key = LocalStorage(get_settings().storage_root).save(PDF, prefix=f"resumes/{reference}", suffix=".pdf")
    with session_scope() as session:
        applicant = Applicant(
            reference=reference, name="Ada Lovelace", email=f"{reference}@example.com",
            github_login=github_login, status="submitted",
        )
        session.add(applicant)
        session.flush()
        session.add(ApplicantDocument(
            applicant_id=applicant.id, document_type="resume", storage_key=key,
            original_filename="cv.pdf", mime_type="application/pdf", size_bytes=len(PDF),
        ))
        return applicant.id


def _fake_profile(reference: str):
    from src.profile_agent.profile_models import ApplicantProfile, SkillEvidence
    from src.profile_agent.profile_models import ApplicantSkill as PSkill

    return ApplicantProfile(
        applicant_id=reference,
        skills=[PSkill(canonical_skill="Python", category="Language", claimed_level=2,
                       confidence=0.9, evidence=[SkillEvidence(source="resume", text="Built things in Python")],
                       reasoning="resume lists Python projects")],
        domains=["backend"], interests=[], education=[], work_experience=[],
    )


def _fake_github_profile(reference: str) -> GitHubProfile:
    # A repo with a strong python signal - the rules engine reads this as
    # verified (level 2), so applicant_skills ends up GitHub-verified.
    repo: RepoRecord = _repo("api")
    return _profile(repo).model_copy(update={"applicant_id": reference})


@pytest.fixture
def stub_agents(monkeypatch):
    """Stub the profile agent and GitHub collection; leave the evidence agent real."""
    calls = {"collect_user": 0}

    def fake_evaluate_resume(resume_path, applicant_id=None, **kwargs):
        assert resume_path is not None
        return _fake_profile(applicant_id)

    def fake_collect_user(client, login, *, max_repos=None, stratum=None, persist=True):
        calls["collect_user"] += 1
        assert persist is False  # the backend must ask for in-memory collection
        return {"login": login, "fake": True}

    def fake_build_profile(bundle, applicant_id):
        assert bundle.get("fake") is True
        return _fake_github_profile(applicant_id)

    monkeypatch.setattr("src.profile_agent.profile_graph.evaluate_resume", fake_evaluate_resume)
    monkeypatch.setattr("generator.github.collector.collect_user", fake_collect_user)
    monkeypatch.setattr("generator.github.normalize.build_profile", fake_build_profile)
    return calls


def _tree(*roots):
    return {str(p) for root in roots if root.exists() for p in root.rglob("*")}


def test_process_applicant_persists_everything_and_writes_no_files(db, stub_agents):
    from generator.config import CACHE_DIR, PROFILES_DIR, RAW_DIR

    from backend.services.processing import process_applicant

    before = _tree(PROFILES_DIR, RAW_DIR, CACHE_DIR)
    applicant_id = _make_applicant("testapplicant0001")

    process_applicant(applicant_id)

    after = _tree(PROFILES_DIR, RAW_DIR, CACHE_DIR)
    assert after == before, "processing must not write under legacy/githubs/ or .cache/"

    with session_scope() as session:
        applicant = session.get(Applicant, applicant_id)
        assert applicant.status == "ready", applicant.status_detail
        assert applicant.github_snapshot is not None
        assert applicant.github_snapshot["applicant_id"] == "testapplicant0001"

        skills = session.query(ApplicantSkill).filter_by(applicant_id=applicant_id).all()
        by_id = {s.skill_id: s for s in skills}
        assert "python" in by_id
        python = by_id["python"]
        assert python.verification_status is not None  # verified against GitHub, not left unverified
        assert python.observed_level is not None

    assert stub_agents["collect_user"] == 1

    # Reprocessing must not re-scrape GitHub: the snapshot is already in the DB.
    process_applicant(applicant_id)
    assert stub_agents["collect_user"] == 1

    with session_scope() as session:
        applicant = session.get(Applicant, applicant_id)
        assert applicant.status == "ready"


def test_reverify_github_reuses_the_profile_and_replaces_skipped_stages(db, client, stub_agents, monkeypatch):
    """GitHub rate-limited on first processing -> skipped with a readable reason;
    re-verification later collects GitHub and reruns evidence + resolve without
    calling the resume LLM again."""
    import generator.github.collector as collector
    from generator.github.client import RateLimited

    import src.profile_agent.profile_graph as profile_graph
    from backend.api import routes_manager
    from backend.services.processing import process_applicant

    real_collect = collector.collect_user
    resume_calls = {"n": 0}
    real_evaluate = profile_graph.evaluate_resume

    def counting_evaluate(*args, **kwargs):
        resume_calls["n"] += 1
        return real_evaluate(*args, **kwargs)

    def limited(*args, **kwargs):
        raise RateLimited("rate limit exhausted")

    monkeypatch.setattr(profile_graph, "evaluate_resume", counting_evaluate)
    monkeypatch.setattr(collector, "collect_user", limited)
    applicant_id = _make_applicant("testapplicant0002")
    process_applicant(applicant_id)

    detail = client.get(f"/api/manager/applicants/{applicant_id}").json()
    stages = {s["agent_type"]: s for s in detail["stages"]}
    assert detail["status"] == "ready"
    assert [s["agent_type"] for s in detail["stages"]] == ["profile", "github", "evidence", "resolve"]
    assert stages["github"]["status"] == "skipped"
    assert "rate limit" in stages["github"]["message"].lower()
    assert "RateLimited" in stages["github"]["error"]
    assert stages["evidence"]["status"] == "skipped"
    assert detail["skills"][0]["observed_level"] is None

    # Full outputs are served per run, not inlined in the (polled) detail.
    profile_run = client.get(
        f"/api/manager/applicants/{applicant_id}/agent-runs/{stages['profile']['run_id']}"
    ).json()
    assert profile_run["output"]["skills"][0]["canonical_skill"] == "Python"
    assert "output" not in stages["profile"] and stages["profile"]["has_output"]

    # Quota exhausted: refused up front with the reason.
    def no_quota():
        raise routes_manager.GitHubUnavailable("GitHub quota for anonymous access is nearly used up")

    monkeypatch.setattr(routes_manager, "check_github_available", no_quota)
    r = client.post(f"/api/manager/applicants/{applicant_id}/reverify-github")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "github_unavailable"
    assert "quota" in r.json()["error"]["message"]

    # Quota back: collection works now.
    monkeypatch.setattr(routes_manager, "check_github_available", lambda: {"remaining": 5000})
    monkeypatch.setattr(collector, "collect_user", real_collect)
    r = client.post(f"/api/manager/applicants/{applicant_id}/reverify-github")
    assert r.status_code == 202, r.text

    detail = client.get(f"/api/manager/applicants/{applicant_id}").json()
    stages = {s["agent_type"]: s for s in detail["stages"]}
    assert detail["status"] == "ready"
    assert len(detail["stages"]) == 4
    assert stages["github"]["status"] == "succeeded" and stages["github"]["has_output"]
    assert stages["evidence"]["status"] == "succeeded"
    assert stages["resolve"]["started_at"] > stages["github"]["started_at"]
    assert stages["profile"]["started_at"] < stages["github"]["started_at"]
    assert detail["skills"][0]["observed_level"] is not None
    assert resume_calls["n"] == 1


def test_reverify_github_refusals(db, client, stub_agents):
    no_github = _make_applicant("testapplicant0003", github_login=None)
    r = client.post(f"/api/manager/applicants/{no_github}/reverify-github")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_github"

    never_profiled = _make_applicant("testapplicant0004")
    r = client.post(f"/api/manager/applicants/{never_profiled}/reverify-github")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_profile"

    r = client.get(f"/api/manager/applicants/{never_profiled}/agent-runs/{uuid.uuid4()}")
    assert r.status_code == 404
