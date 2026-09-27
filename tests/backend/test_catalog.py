"""Catalog agent endpoint: suggestions only, never writes; clear errors."""

import uuid


def _project(client, name, description):
    r = client.post("/api/manager/projects", json={"name": name, "description": description})
    assert r.status_code == 201, r.text
    return r.json()


def test_unknown_project_is_404(client):
    r = client.post(f"/api/manager/projects/{uuid.uuid4()}/suggest-requirements")
    assert r.status_code == 404


def test_short_description_is_refused_before_any_model_call(client, monkeypatch):
    import backend.services.catalog as catalog

    def no_client():
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(catalog, "_client", no_client)
    p = _project(client, "Tiny", "calc")
    r = client.post(f"/api/manager/projects/{p['id']}/suggest-requirements")
    assert r.status_code == 422 and r.json()["error"]["code"] == "catalog_failed"
    assert "description" in r.json()["error"]["message"]


def test_no_model_configured_is_503(client, monkeypatch):
    for name in ("LLM_GATEWAY_URL", "LLM_GATEWAY_API_KEY", "LLM_MODEL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    p = _project(client, "Needs Model", "A web calculator built with Next.js and unit tests.")
    r = client.post(f"/api/manager/projects/{p['id']}/suggest-requirements")
    assert r.status_code == 503 and r.json()["error"]["code"] == "catalog_unavailable"


def test_suggestion_is_returned_and_nothing_is_saved(client, monkeypatch):
    import backend.services.catalog as catalog

    async def fake(request_id, name, description):
        assert name == "Calculator" and "Next.js" in description
        return {
            "provider": "gateway",
            "summary": "A calculator web app.",
            "requirements": [
                {"skill_id": "nextjs", "skill_name": "Next.js", "requirement_type": "hard_requirement",
                 "required_level": 2, "level_suggested": True, "weight": 1.0, "confidence": 0.9,
                 "evidence_text": "built with Next.js", "decision_basis": "named stack"},
            ],
            "unresolved": [{"raw_skill": "abacus", "requirement_type": "preferred", "candidate_skill_ids": []}],
            "uncertainties": [],
            "issues": [],
        }

    monkeypatch.setattr(catalog, "suggest_requirements", fake)
    p = _project(client, "Calculator", "A web calculator built with Next.js and unit tests.")
    r = client.post(f"/api/manager/projects/{p['id']}/suggest-requirements")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requirements"][0]["skill_id"] == "nextjs"
    assert body["unresolved"][0]["raw_skill"] == "abacus"
    assert client.get(f"/api/manager/projects/{p['id']}").json()["roles"] == []
