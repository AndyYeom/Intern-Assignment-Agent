"""API flow: apply -> (stubbed) processing -> projects -> assignment run -> review."""

import uuid

import pytest

from backend.db import session_scope
from backend.db.models import Applicant
from backend.services.persistence import replace_applicant_skills
from backend.services.skill_resolution import ResolvedSkill

PDF = b"%PDF-1.4\n% test resume\n"


def fake_processing(skill_levels):
    """Replace the LLM pipeline: give each applicant fixed resolved skills."""

    def process(applicant_id: uuid.UUID) -> None:
        with session_scope() as s:
            a = s.get(Applicant, applicant_id)
            replace_applicant_skills(
                s, a, [ResolvedSkill(skill_id=k, final_level=v, claimed_level=v) for k, v in skill_levels.items()]
            )
            a.status = "ready"

    return process


def apply(client, name, email, github="https://github.com/octocat"):
    return client.post(
        "/api/applications",
        data={"name": name, "email": email, "github_url": github},
        files={"resume": ("cv.pdf", PDF, "application/pdf")},
    )


@pytest.fixture
def stub_pipeline(monkeypatch):
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2, "sql": 1}))


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ok", "database": True}


def test_application_is_persisted_and_processed(client, stub_pipeline):
    r = apply(client, "Ada Lovelace", "ada@example.com")
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    # TestClient runs background tasks before returning.
    public = client.get(f"/api/applications/{app_id}").json()
    assert public["status"] == "ready" and "model" not in public["message"].lower()

    detail = client.get(f"/api/manager/applicants/{app_id}").json()
    assert detail["github_login"] == "octocat"
    assert {s["skill_id"]: s["final_level"] for s in detail["skills"]} == {"python": 2, "sql": 1}
    doc = detail["documents"][0]
    assert client.get(doc["download_path"]).content == PDF


def test_application_validation_and_duplicates(client, stub_pipeline):
    assert apply(client, "A", "a@example.com").status_code == 201
    dup = apply(client, "A2", "A@EXAMPLE.COM")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_email"
    bad = client.post(
        "/api/applications",
        data={"name": "B", "email": "b@example.com", "github_url": "https://github.com/b"},
        files={"resume": ("cv.txt", b"hello", "text/plain")},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["details"][0]["field"] == "resume"
    assert client.get(f"/api/applications/{uuid.uuid4()}").status_code == 404


def _project(client, name, roles):
    r = client.post("/api/manager/projects", json={"name": name, "roles": roles})
    assert r.status_code == 201, r.text
    return r.json()


def role(name, capacity, *reqs):
    return {
        "name": name,
        "capacity": capacity,
        "requirements": [
            {"skill_id": s, "required_level": lvl, "requirement_type": t} for s, lvl, t in reqs
        ],
    }


def test_assignment_run_persists_and_respects_role_capacity(client, monkeypatch):
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2, "sql": 2}))
    for i in range(5):
        assert apply(client, f"Applicant {i}", f"p{i}@example.com").status_code == 201
    project = _project(
        client,
        "Data Portal",
        [
            role("Backend", 2, ("python", 2, "hard_requirement"), ("postgresql", 2, "learning_opportunity")),
            role("Data", 1, ("sql", 1, "hard_requirement")),
        ],
    )
    run = client.post("/api/manager/assignment-runs", json={})
    assert run.status_code == 202, run.text
    detail = client.get(f"/api/manager/assignment-runs/{run.json()['id']}").json()
    assert detail["status"] == "completed", detail["error"]
    assert detail["applicant_count"] == 5 and detail["role_count"] == 2

    by_role = {}
    for a in detail["assignments"]:
        by_role.setdefault(a["role"]["name"], []).append(a)
        assert a["project"]["id"] == project["id"] and a["status"] == "proposed"
        assert a["reason"]["summary"]
    capacity = {r["name"]: r["capacity"] for r in project["roles"]}
    assert all(len(v) <= capacity[k] for k, v in by_role.items())
    assert len(detail["assignments"]) + len(detail["unassigned"]) == 5
    util = detail["utilization"][0]
    assert util["capacity"] == 3 and util["filled"] == len(detail["assignments"])

    # Runs are history: listed, and scores stored for every applicant x role.
    assert client.get("/api/manager/assignment-runs").json()[0]["id"] == detail["id"]
    scored = client.get(f"/api/manager/applicants/{detail['assignments'][0]['applicant']['id']}").json()
    assert len(scored["scores"]) == 2 and scored["assignment"] is not None

    # Review: approve; moving someone into a role that is at capacity is refused.
    first = detail["assignments"][0]
    ok = client.patch(f"/api/manager/assignments/{first['id']}", json={"status": "approved", "note": "ok"})
    assert ok.json()["status"] == "approved" and ok.json()["note"] == "ok"
    target = first["role"]
    client.patch(f"/api/manager/roles/{target['id']}", json={"capacity": len(by_role[target["name"]])})
    other = next((a for a in detail["assignments"] if a["role"]["id"] != target["id"]), None)
    if other is None:  # everyone landed in one role; move within capacity instead
        other_role = next(r for r in project["roles"] if r["id"] != target["id"])
        moved = client.patch(f"/api/manager/assignments/{first['id']}", json={"role_id": other_role["id"]})
        assert moved.status_code == 200
        full = other_role
    else:
        refused = client.patch(f"/api/manager/assignments/{other['id']}", json={"role_id": target["id"]})
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "role_full"
        full = target

    # A role that is part of run history cannot be deleted.
    assert client.delete(f"/api/manager/roles/{full['id']}").status_code == 409


def test_override_keeps_the_solver_choice(client, monkeypatch):
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    apply(client, "Solo", "solo@example.com")
    project = _project(
        client,
        "Two Roles",
        [role("A", 1, ("python", 2, "hard_requirement")), role("B", 1, ("python", 1, "preferred"))],
    )
    run_id = client.post("/api/manager/assignment-runs", json={}).json()["id"]
    detail = client.get(f"/api/manager/assignment-runs/{run_id}").json()
    assert len(detail["assignments"]) == 1
    a = detail["assignments"][0]
    other = next(r for r in project["roles"] if r["id"] != a["role"]["id"])
    moved = client.patch(f"/api/manager/assignments/{a['id']}", json={"role_id": other["id"]}).json()
    assert moved["overridden"] is True
    assert moved["role"]["id"] == other["id"] and moved["solver_role"]["id"] == a["role"]["id"]


def test_run_without_ready_applicants_is_rejected(client):
    _project(client, "Empty", [role("A", 1, ("python", 1, "hard_requirement"))])
    r = client.post("/api/manager/assignment-runs", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_run"


def test_project_and_role_editing(client):
    p = _project(client, "Editable", [role("A", 1, ("python", 1, "hard_requirement"))])
    assert client.post("/api/manager/projects", json={"name": "EDITABLE"}).status_code == 409
    rid = p["roles"][0]["id"]
    r = client.patch(
        f"/api/manager/roles/{rid}",
        json={"capacity": 3, "requirements": [{"skill_id": "react", "required_level": 2, "requirement_type": "preferred"}]},
    ).json()
    assert r["capacity"] == 3 and [q["skill_id"] for q in r["requirements"]] == ["react"]
    bad = client.patch(
        f"/api/manager/roles/{rid}",
        json={"requirements": [{"skill_id": "cobol", "required_level": 1, "requirement_type": "preferred"}]},
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_skill"
    assert client.patch(f"/api/manager/projects/{p['id']}", json={"status": "archived"}).json()["status"] == "archived"
    assert client.delete(f"/api/manager/roles/{rid}").status_code == 204
