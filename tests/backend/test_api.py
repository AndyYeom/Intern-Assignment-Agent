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


def test_approved_placements_carry_over_to_later_runs(client, monkeypatch):
    """Approving commits a seat: the next run skips placed applicants and only
    offers the remaining seats; rejecting the approval releases both."""
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    for i in range(4):
        assert apply(client, f"Carry {i}", f"carry{i}@example.com").status_code == 201
    project = _project(client, "Carry Over", [role("Dev", 2, ("python", 2, "hard_requirement"))])
    dev = project["roles"][0]

    def run():
        r = client.post("/api/manager/assignment-runs", json={})
        assert r.status_code == 202, r.text
        return client.get(f"/api/manager/assignment-runs/{r.json()['id']}").json()

    first = run()
    assert len(first["assignments"]) == 2
    approved = first["assignments"][0]
    ok = client.patch(f"/api/manager/assignments/{approved['id']}", json={"status": "approved"})
    assert ok.status_code == 200

    # Shown as the applicant's placement, and filterable.
    placed_id = approved["applicant"]["id"]
    assigned = client.get("/api/manager/applicants", params={"placement": "assigned"}).json()
    assert [a["id"] for a in assigned] == [placed_id]
    assert assigned[0]["assignment"]["status"] == "approved"
    assert len(client.get("/api/manager/applicants", params={"placement": "unassigned"}).json()) == 3

    # Second run: the placed applicant is left out and only one seat is offered.
    second = run()
    assert second["applicant_count"] == 3
    assert second["configuration"]["role_seats"] == {dev["id"]: 1}
    assert second["configuration"]["excluded_placed_applicants"] == 1
    assert len(second["assignments"]) == 1
    assert placed_id not in {a["applicant"]["id"] for a in second["assignments"]}
    util = second["utilization"][0]["roles"][0]
    assert util["capacity"] == 1 and util["filled_before"] == 1

    # The earlier approval still wins over the newer run's proposals.
    detail = client.get(f"/api/manager/applicants/{placed_id}").json()
    assert detail["assignment"]["run_id"] == first["id"]

    # Approving a second person from run 1 would overfill across runs? No: 2 seats.
    other_first = first["assignments"][1]
    new = second["assignments"][0]
    assert client.patch(f"/api/manager/assignments/{new['id']}", json={"status": "approved"}).status_code == 200
    full = client.patch(f"/api/manager/assignments/{other_first['id']}", json={"status": "approved"})
    assert full.status_code == 409 and full.json()["error"]["code"] == "role_full"

    # Role full: a further run has nothing to assign to.
    full_role = client.get(f"/api/manager/assignment-runs/{second['id']}").json()["utilization"][0]["roles"][0]
    assert full_role["filled_before"] == 1
    blocked = client.post("/api/manager/assignment-runs", json={})
    assert blocked.status_code == 422 and "filled" in blocked.json()["error"]["message"]

    # Rejecting an approval releases the seat and the applicant.
    client.patch(f"/api/manager/assignments/{approved['id']}", json={"status": "rejected"})
    third = run()
    assert third["configuration"]["role_seats"] == {dev["id"]: 1}
    assert placed_id in third["configuration"]["applicant_ids"]


def test_delete_project_removes_its_roles_too(client):
    p = _project(client, "Deletable", [role("A", 1, ("python", 1, "hard_requirement"))])
    rid = p["roles"][0]["id"]
    assert client.delete(f"/api/manager/projects/{p['id']}").status_code == 204
    assert client.get(f"/api/manager/projects/{p['id']}").status_code == 404
    assert client.patch(f"/api/manager/roles/{rid}", json={"capacity": 2}).status_code == 404


def test_delete_project_unknown_id_is_404(client):
    assert client.delete(f"/api/manager/projects/{uuid.uuid4()}").status_code == 404


def test_delete_project_blocked_by_assignment_history(client, monkeypatch):
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    apply(client, "Placed", "placed@example.com")
    project = _project(client, "In Use", [role("Dev", 1, ("python", 2, "hard_requirement"))])
    run = client.post("/api/manager/assignment-runs", json={})
    assert run.status_code == 202, run.text
    detail = client.get(f"/api/manager/assignment-runs/{run.json()['id']}").json()
    assert len(detail["assignments"]) == 1

    blocked = client.delete(f"/api/manager/projects/{project['id']}")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "project_in_use"


def test_delete_project_blocked_by_role_score_only(client, monkeypatch):
    """A project that a run only scored against (never actually filled) is still
    blocked: ApplicantRoleScore rows reference it even without an Assignment."""
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    apply(client, "Scored", "scored@example.com")
    _project(client, "Placed", [role("A", 1, ("python", 1, "preferred"))])
    unused = _project(client, "Unfilled", [role("B", 1, ("sql", 2, "hard_requirement"))])
    run = client.post("/api/manager/assignment-runs", json={})
    assert run.status_code == 202, run.text
    detail = client.get(f"/api/manager/assignment-runs/{run.json()['id']}").json()
    assert len(detail["assignments"]) == 1
    assert all(a["project"]["id"] != unused["id"] for a in detail["assignments"])
    scored = client.get(f"/api/manager/applicants/{detail['assignments'][0]['applicant']['id']}").json()
    assert any(sc["project_id"] == unused["id"] for sc in scored["scores"])

    blocked = client.delete(f"/api/manager/projects/{unused['id']}")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "project_in_use"


def test_manual_assignment_override(client, monkeypatch):
    """The manager can place an unassigned applicant into an open seat by hand,
    even a role the solver could never give them (a failed hard requirement)."""
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    for name in ("Ann", "Bob", "Dan"):
        assert apply(client, name, f"{name.lower()}@example.com").status_code == 201
    monkeypatch.setattr(public, "process_applicant", fake_processing({"sql": 2}))
    assert apply(client, "Carol", "carol@example.com").status_code == 201

    project = _project(
        client,
        "Override Co",
        [
            role("Analyst", 1, ("python", 2, "hard_requirement")),
            role("DBA", 2, ("sql", 2, "hard_requirement")),
        ],
    )
    roles_by_name = {r["name"]: r for r in project["roles"]}

    run_id = client.post("/api/manager/assignment-runs", json={}).json()["id"]
    detail = client.get(f"/api/manager/assignment-runs/{run_id}").json()
    assert detail["status"] == "completed", detail["error"]

    # DBA has 2 seats but only Carol (sql) meets its hard requirement, so one
    # seat is never filled by the solver; the three python-only applicants
    # compete for Analyst's single seat, leaving two unassigned.
    assert len(detail["unassigned"]) == 2

    target = detail["unassigned"][0]
    assert [b["skill_id"] for b in target["skills"]] == ["python"]
    assert target["skills"][0]["level"] == 2
    assert target["candidate_role_count"] == 1

    dba_option = next(o for o in target["options"] if o["role_id"] == roles_by_name["DBA"]["id"])
    assert dba_option["open_seats"] == 1 and dba_option["candidate"] is False
    analyst_option = next(o for o in target["options"] if o["role_id"] == roles_by_name["Analyst"]["id"])
    assert analyst_option["open_seats"] == 0

    created = client.post(
        f"/api/manager/assignment-runs/{run_id}/assignments",
        json={"applicant_id": target["id"], "role_id": roles_by_name["DBA"]["id"]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "approved" and body["manual"] is True
    assert body["role"]["id"] == roles_by_name["DBA"]["id"]

    after = client.get(f"/api/manager/assignment-runs/{run_id}").json()
    assert target["id"] not in {u["id"] for u in after["unassigned"]}
    dba_util = next(
        r for p in after["utilization"] for r in p["roles"] if r["role_id"] == roles_by_name["DBA"]["id"]
    )
    assert dba_util["filled"] == 2

    # DBA is now full: the other leftover applicant can't get in.
    assert len(after["unassigned"]) == 1
    other = after["unassigned"][0]
    full = client.post(
        f"/api/manager/assignment-runs/{run_id}/assignments",
        json={"applicant_id": other["id"], "role_id": roles_by_name["DBA"]["id"]},
    )
    assert full.status_code == 409 and full.json()["error"]["code"] == "role_full"

    # Assigning someone who already has a live row in this run is refused...
    analyst_holder = next(a for a in after["assignments"] if a["role"]["id"] == roles_by_name["Analyst"]["id"])
    dup = client.post(
        f"/api/manager/assignment-runs/{run_id}/assignments",
        json={"applicant_id": analyst_holder["applicant"]["id"], "role_id": roles_by_name["DBA"]["id"]},
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_assigned"

    # ...but rejecting that row frees it up for reassignment, reusing the row.
    client.patch(f"/api/manager/assignments/{analyst_holder['id']}", json={"status": "rejected"})
    reassigned = client.post(
        f"/api/manager/assignment-runs/{run_id}/assignments",
        json={"applicant_id": analyst_holder["applicant"]["id"], "role_id": roles_by_name["Analyst"]["id"]},
    )
    assert reassigned.status_code == 201, reassigned.text
    assert reassigned.json()["id"] == analyst_holder["id"]


def test_manual_assign_blocked_by_placement_in_another_run(client, monkeypatch):
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    assert apply(client, "Placed Elsewhere", "elsewhere@example.com").status_code == 201

    role_a = role("RA", 1, ("python", 2, "hard_requirement"))
    role_b = role("RB", 1, ("python", 2, "hard_requirement"))
    _project(client, "Run A Project", [role_a])
    run_a = client.post("/api/manager/assignment-runs", json={}).json()["id"]
    detail_a = client.get(f"/api/manager/assignment-runs/{run_a}").json()
    applicant_id = detail_a["assignments"][0]["applicant"]["id"]

    proj_b = _project(client, "Run B Project", [role_b])
    run_b = client.post("/api/manager/assignment-runs", json={}).json()["id"]
    detail_b = client.get(f"/api/manager/assignment-runs/{run_b}").json()

    # Approve the placement from run A first.
    a1 = detail_a["assignments"][0]
    assert client.patch(f"/api/manager/assignments/{a1['id']}", json={"status": "approved"}).status_code == 200

    # Free up run B's seat (whatever the solver did with the same applicant there).
    b1 = detail_b["assignments"][0]
    client.patch(f"/api/manager/assignments/{b1['id']}", json={"status": "rejected"})

    blocked = client.post(
        f"/api/manager/assignment-runs/{run_b}/assignments",
        json={"applicant_id": applicant_id, "role_id": proj_b["roles"][0]["id"]},
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "already_placed"


def test_manual_assign_rejects_run_not_completed_or_unknown_ids(client, monkeypatch):
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    assert apply(client, "Solo", "manualsolo@example.com").status_code == 201
    project = _project(client, "Manual Only", [role("A", 1, ("python", 2, "hard_requirement"))])
    run_id = client.post("/api/manager/assignment-runs", json={}).json()["id"]
    detail = client.get(f"/api/manager/assignment-runs/{run_id}").json()
    applicant_id = detail["assignments"][0]["applicant"]["id"]

    bad_role = client.post(
        f"/api/manager/assignment-runs/{run_id}/assignments",
        json={"applicant_id": applicant_id, "role_id": str(uuid.uuid4())},
    )
    assert bad_role.status_code == 422 and bad_role.json()["error"]["code"] == "invalid_role"

    bad_applicant = client.post(
        f"/api/manager/assignment-runs/{run_id}/assignments",
        json={"applicant_id": str(uuid.uuid4()), "role_id": project["roles"][0]["id"]},
    )
    assert bad_applicant.status_code == 422 and bad_applicant.json()["error"]["code"] == "invalid_applicant"


def test_one_approved_placement_per_applicant(client, monkeypatch):
    import backend.api.routes_public as public

    monkeypatch.setattr(public, "process_applicant", fake_processing({"python": 2}))
    apply(client, "Twice", "twice@example.com")
    _project(client, "First", [role("A", 1, ("python", 2, "hard_requirement"))])
    first = client.post("/api/manager/assignment-runs", json={}).json()["id"]
    a1 = client.get(f"/api/manager/assignment-runs/{first}").json()["assignments"][0]
    client.patch(f"/api/manager/assignments/{a1['id']}", json={"status": "approved"})
    client.patch(f"/api/manager/assignments/{a1['id']}", json={"status": "proposed"})  # un-approve

    second = client.post("/api/manager/assignment-runs", json={}).json()["id"]
    a2 = client.get(f"/api/manager/assignment-runs/{second}").json()["assignments"][0]
    assert client.patch(f"/api/manager/assignments/{a2['id']}", json={"status": "approved"}).status_code == 200
    again = client.patch(f"/api/manager/assignments/{a1['id']}", json={"status": "approved"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_placed"
