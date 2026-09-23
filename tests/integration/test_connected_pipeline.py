"""Verify real component boundaries using existing saved extraction results."""

import asyncio

import pytest
from pipeline.integrated import ROOT, RunInput, matching_student, read_json, run
from src.evidence_agent import evaluate_github
from src.profile_agent.profile_models import ApplicantProfile

from project_catalog_agent.taxonomy.json_repository import JsonTaxonomyRepository


def inputs():
    return RunInput.model_validate(read_json(ROOT / "data/integration-demo.json"))


def test_replay_carries_same_applicants_through_all_components(tmp_path):
    folder = tmp_path / "run"
    result = asyncio.run(run(inputs(), folder, "replay"))
    assert set(result.assignments) == {"applicant0004", "applicant0006"}
    assert result.unassigned_students == []
    data = read_json(folder / "matching-input.json")
    assert all(1 <= s["level"] <= 3 for a in data["students"] for s in a["skills"])
    assert all(
        1 <= r["required_level"] <= 3
        for p in data["projects"]
        for r in p["requirements"]
    )
    assert len(read_json(folder / "scores.json")) == 4
    status = read_json(folder / "status.json")
    assert status["review_status"] == "pending"
    assert not status["published"]
    assert not status["live_model_validation"]
    assert read_json(folder / "assignment-draft.json")["review_status"] == "pending"


def test_does_not_reuse_stale_artifacts(tmp_path):
    with pytest.raises(FileExistsError):
        asyncio.run(run(inputs(), tmp_path, "replay"))


def test_rejects_duplicate_applicants():
    data = inputs().model_dump(mode="json")
    data["applicants"].append(data["applicants"][0])
    with pytest.raises(ValueError, match="duplicate"):
        RunInput.model_validate(data)


def test_unresolved_project_stops_before_scoring(tmp_path):
    data = inputs()
    data.projects[0].replay_extraction.requirements[0].raw_skill = "UnknownXYZSkill"
    folder = tmp_path / "unresolved"
    with pytest.raises(ValueError, match="review required"):
        asyncio.run(run(data, folder, "replay"))
    assert read_json(folder / "status.json")["status"] == "failed"
    assert not (folder / "assignment-draft.json").exists()


def test_evidence_id_mismatch_is_rejected():
    profile = ApplicantProfile.model_validate(
        read_json(ROOT / "output/applicant0004_profile.json")
    )
    report = evaluate_github(profile.applicant_id, profile, use_llm=False)
    report.applicant_id = "different"
    with pytest.raises(ValueError, match="mismatch"):
        matching_student(
            profile, report, JsonTaxonomyRepository(ROOT / "data/taxonomy.json")
        )


def test_insufficient_capacity_is_explicit(tmp_path):
    data = inputs()
    # Both students can use Java, but there is only one seat.
    data.projects = data.projects[:1]
    data.projects[0].capacity = 1
    folder = tmp_path / "limited"
    result = asyncio.run(run(data, folder, "replay"))
    assert len(result.unassigned_students) == 1
    assert read_json(folder / "status.json")["unassigned"] == result.unassigned_students


def test_live_mode_uses_live_profile_and_catalog_boundaries(tmp_path, monkeypatch):
    from src.profile_agent import profile_graph

    from project_catalog_agent.llm.openai_client import OpenAIStructuredLLMClient

    calls = []
    data = inputs()

    def profile_call(resume_path, applicant_id, portfolio_path):
        calls.append(("profile", applicant_id))
        return ApplicantProfile.model_validate(
            read_json(ROOT / f"output/{applicant_id}_profile.json")
        )

    class FakeNetworkClient:
        async def generate_structured(
            self, *, system_prompt, user_prompt, response_model
        ):
            calls.append(("catalog", response_model.__name__))
            item = next(
                p for p in data.projects if p.request.project_name in user_prompt
            )
            return item.replay_extraction

    monkeypatch.setattr(profile_graph, "create_profile_llm", lambda: object())
    monkeypatch.setattr(profile_graph, "evaluate_resume", profile_call)
    monkeypatch.setattr(
        OpenAIStructuredLLMClient, "from_settings", lambda settings: FakeNetworkClient()
    )
    # Exercise the actual evidence graph without any network fallback.
    import pipeline.integrated as integrated

    monkeypatch.setattr(
        integrated,
        "evaluate_github",
        lambda applicant_id, profile, use_llm: evaluate_github(
            applicant_id, profile, use_llm=False
        ),
    )
    result = asyncio.run(run(data, tmp_path / "live-mocked", "live"))
    assert not result.unassigned_students
    assert sum(c[0] == "profile" for c in calls) == 2
    assert sum(c[0] == "catalog" for c in calls) == 2


def test_missing_live_credentials_fail_before_processing(tmp_path, monkeypatch):
    for name in (
        "LLM_GATEWAY_URL",
        "LLM_GATEWAY_API_KEY",
        "LLM_MODEL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.setenv(name, "")
    folder = tmp_path / "missing-credentials"
    with pytest.raises(Exception, match="Missing required gateway configuration"):
        asyncio.run(run(inputs(), folder, "live"))
    assert read_json(folder / "status.json")["status"] == "failed"
    assert not (folder / "profiles.json").exists()
