"""Manager overrides of skills and evidence: edits re-derive levels with the
pipeline's rules, deletes are soft, and overridden skills survive reprocessing
and are what matching sees."""

import uuid

import pytest
from sqlalchemy import select

from backend.db import session_scope
from backend.db.models import Applicant, ApplicantSkill, ApplicantSkillEvidence
from backend.services.persistence import replace_applicant_skills
from backend.services.skill_resolution import EvidenceItem, ResolvedSkill


def _resolved(skill_id, claimed, observed=None, status=None, final=None):
    return ResolvedSkill(
        skill_id=skill_id, claimed_level=claimed, observed_level=observed,
        verification_status=status, final_level=final if final is not None else claimed,
        claim_summary=f"claims {skill_id}",
        evidence=[EvidenceItem(source_type="resume", reference="page 1", excerpt=f"used {skill_id}")],
    )


@pytest.fixture
def applicant(db):
    with session_scope() as s:
        a = Applicant(reference="override0001", name="Ada", email="ada.override@example.com", status="ready")
        s.add(a)
        s.flush()
        replace_applicant_skills(s, a, [
            _resolved("python", 2, observed=2, status="verified", final=2),
            _resolved("sql", 3, observed=None, status="not_observed", final=3),
            _resolved("docker", 1),
        ])
        return a.id


def url(aid, *parts):
    return "/api/manager/applicants/" + "/".join([str(aid), *parts])


def skills(client, aid):
    return {k["skill_id"]: k for k in client.get(url(aid)).json()["skills"]}


def test_observed_level_edit_rederives_status_and_final_level(client, applicant):
    # sql claimed Advanced, nothing observed -> manager observes Entry: conflicting.
    r = client.patch(url(applicant, "skills", "sql"), json={"observed_level": 1})
    assert r.status_code == 200, r.text
    sql = r.json()
    assert sql["observed_level"] == 1
    assert sql["verification_status"] == "conflicting" and sql["flag"] == "conflicting"
    assert sql["final_level"] == 1 and sql["edited_at"] is not None

    # One level short -> partially verified, final at most observed + 1.
    sql = client.patch(url(applicant, "skills", "sql"), json={"observed_level": 2}).json()
    assert sql["verification_status"] == "partially_verified" and sql["final_level"] == 3

    # Cleared -> not observed: the claim stands, flagged unverified.
    sql = client.patch(url(applicant, "skills", "sql"), json={"observed_level": None}).json()
    assert sql["observed_level"] is None
    assert sql["verification_status"] == "not_observed" and sql["flag"] == "unverified"
    assert sql["final_level"] == 3

    # Text edits persist and leave levels alone.
    python = client.patch(
        url(applicant, "skills", "python"),
        json={"claim_summary": "Built two APIs", "verification_summary": "Checked repo"},
    ).json()
    assert python["claim_summary"] == "Built two APIs" and python["verification_summary"] == "Checked repo"
    assert python["final_level"] == 2 and python["verification_status"] == "verified"
    assert skills(client, applicant)["python"]["claim_summary"] == "Built two APIs"


def test_soft_delete_hides_skill_everywhere_and_add_restores(client, applicant):
    assert client.delete(url(applicant, "skills", "docker")).status_code == 204
    assert "docker" not in skills(client, applicant)
    listed = next(a for a in client.get("/api/manager/applicants").json() if a["id"] == str(applicant))
    assert listed["skill_count"] == 2
    with session_scope() as s:  # still in the table, marked deleted
        row = s.scalar(select(ApplicantSkill).where(ApplicantSkill.skill_id == "docker"))
        assert row is not None and row.deleted_at is not None
        assert [k.skill_id for k in s.get(Applicant, applicant).skills if k.skill_id == "docker"] == []

    assert client.delete(url(applicant, "skills", "docker")).status_code == 404
    assert client.patch(url(applicant, "skills", "docker"), json={"claim_summary": "x"}).status_code == 404

    # Adding it again restores the row as a manager skill with fresh evidence.
    r = client.post(url(applicant, "skills"), json={"skill_id": "docker", "claimed_level": 2, "observed_level": 2})
    assert r.status_code == 201, r.text
    docker = r.json()
    assert docker["source"] == "manager" and docker["final_level"] == 2
    assert docker["verification_status"] == "verified" and docker["evidence"] == []

    dup = client.post(url(applicant, "skills"), json={"skill_id": "docker", "claimed_level": 1})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_skill"
    unknown = client.post(url(applicant, "skills"), json={"skill_id": "cobol-9000", "claimed_level": 1})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_skill"


def test_evidence_add_edit_soft_delete(client, applicant):
    python = skills(client, applicant)["python"]
    original = python["evidence"][0]

    added = client.post(
        url(applicant, "skills", "python", "evidence"),
        json={"reference": "https://github.com/octocat/api", "excerpt": "Reviewed CI", "level": 2},
    )
    assert added.status_code == 201, added.text
    ev = added.json()
    assert ev["source_type"] == "manager" and ev["edited_at"] is not None

    edited = client.patch(
        url(applicant, "skills", "python", "evidence", original["id"]),
        json={"excerpt": "Used Python daily", "level": 3},
    ).json()
    assert edited["excerpt"] == "Used Python daily" and edited["level"] == 3
    assert edited["reference"] == "page 1"  # untouched field kept

    evidence = skills(client, applicant)["python"]["evidence"]
    assert [e["id"] for e in evidence] == [original["id"], ev["id"]]  # added goes last

    assert client.delete(url(applicant, "skills", "python", "evidence", original["id"])).status_code == 204
    evidence = skills(client, applicant)["python"]["evidence"]
    assert [e["id"] for e in evidence] == [ev["id"]]
    with session_scope() as s:
        assert s.get(ApplicantSkillEvidence, uuid.UUID(original["id"])).deleted_at is not None
    assert skills(client, applicant)["python"]["edited_at"] is not None

    missing = client.patch(url(applicant, "skills", "python", "evidence", original["id"]), json={"level": 1})
    assert missing.status_code == 404


def test_overrides_survive_reprocessing(client, applicant):
    client.patch(url(applicant, "skills", "sql"), json={"observed_level": 1})
    client.delete(url(applicant, "skills", "docker"))
    client.post(url(applicant, "skills"), json={"skill_id": "react", "claimed_level": 2})

    # A fresh agent run proposes different values for every skill.
    with session_scope() as s:
        a = s.get(Applicant, applicant)
        replace_applicant_skills(s, a, [
            _resolved("python", 1, observed=1, status="verified", final=1),
            _resolved("sql", 2, observed=2, status="verified", final=2),
            _resolved("docker", 3, observed=3, status="verified", final=3),
            _resolved("react", 1, observed=1, status="verified", final=1),
            _resolved("go", 2),
        ])

    after = skills(client, applicant)
    assert after["python"]["final_level"] == 1  # not overridden: agent result replaces it
    assert after["sql"]["observed_level"] == 1 and after["sql"]["final_level"] == 1  # manager's value kept
    assert "docker" not in after  # manager deletion kept
    assert after["react"]["source"] == "manager" and after["react"]["claimed_level"] == 2
    assert after["go"]["final_level"] == 2  # new agent skill added


def test_matching_uses_overridden_skills_only(client, applicant):
    from backend import repositories as repo

    client.delete(url(applicant, "skills", "python"))
    client.patch(url(applicant, "skills", "sql"), json={"observed_level": 1})
    with session_scope() as s:
        a = next(x for x in repo.ready_applicants(s) if x.id == applicant)
        levels = {k.skill_id: k.final_level for k in a.skills}
    assert "python" not in levels and levels["sql"] == 1


def test_edits_blocked_while_processing(client, applicant):
    with session_scope() as s:
        s.get(Applicant, applicant).status = "processing"
    r = client.patch(url(applicant, "skills", "sql"), json={"observed_level": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_processing"
