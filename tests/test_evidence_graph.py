"""The evidence agent's graph: after the profile agent, LLM bounded by rules."""
from __future__ import annotations

import json

import pytest

from src.evidence_agent import evidence_graph as eg
from src.evidence_agent.claims import from_profile_payload, to_skill_id
from src.evidence_agent.evidence_prompts import proficiency_taxonomy
from tests.test_evidence import _profile, _repo

API = "https://github.com/u/api"


@pytest.fixture(autouse=True)
def github_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(eg, "PROFILES_DIR", tmp_path)
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    (tmp_path / "applicant0001.json").write_text(_profile(_repo("api")).model_dump_json())


# Shaped like src/profile_agent's ApplicantProfile, free-text skill names included.
# Rules read python at 2 (claim 3: open), postgres absent (settled), unreal unmapped.
PROFILE_A = {"applicant_id": "applicant0001", "skills": [
    {"canonical_skill": "Python", "claimed_level": 3, "evidence": [{"text": "Python (Advanced)"}]},
    {"canonical_skill": "Postgres", "claimed_level": 2},
    {"canonical_skill": "Unreal Engine", "claimed_level": 2},
]}


class FakeLLM:
    model = "fake"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def invoke(self, prompt):
        self.prompts.append(str(prompt))
        return self.answers.pop(0)


def _answer(level, links=(API,), skill="python"):
    return json.dumps({"applicant_id": "applicant0001", "skills": [
        {"skill_id": skill, "observed_level": level, "evidence_strength": "strong",
         "repo_links": list(links), "rationale": "Maintained with fixes over months."}]})


def _by_skill(report):
    return {s.skill_id: s for s in report.skills}


def test_model_judges_only_what_the_rules_cannot_settle():
    llm = FakeLLM(_answer(3))
    report = eg.evaluate_github("applicant0001", PROFILE_A, llm_factory=lambda: llm)
    python, postgres = _by_skill(report)["python"], _by_skill(report)["postgresql"]
    assert (python.method, python.status, python.rule_observed_level) == ("llm", "verified", 2)
    assert postgres.method == "rules" and postgres.status == "not_observed"
    assert report.trace.skills_sent_to_model == ["python"]
    assert "postgresql" in report.trace.skills_decided_by_rules
    assert "postgresql" not in llm.prompts[0].split("<claims>")[1]
    assert report.mode == "mixed" and report.unmapped_claims == ["Unreal Engine"]


def test_no_open_claims_means_no_model_call():
    profile = {"applicant_id": "applicant0001",
               "skills": [{"canonical_skill": "Python", "claimed_level": 1}]}
    report = eg.evaluate_github("applicant0001", profile, llm_factory=lambda: FakeLLM())
    assert report.trace.llm_calls == 0 and report.mode == "rules"


def test_a_verdict_citing_no_real_repository_falls_back_to_rules():
    report = eg.evaluate_github("applicant0001", PROFILE_A, llm_factory=lambda: FakeLLM(
        _answer(3, links=["https://github.com/someone/else"])))
    python = _by_skill(report)["python"]
    assert python.method == "rules" and python.status == "partially_verified"
    assert "cited no repository" in python.notes[0]


def test_the_model_may_say_nothing_or_move_one_level():
    report = eg.evaluate_github("applicant0001", {**PROFILE_A, "skills": [
        {"canonical_skill": "Python", "claimed_level": 3}]},
        llm_factory=lambda: FakeLLM(_answer(None)))
    python = _by_skill(report)["python"]
    assert python.observed_level is None and python.method == "llm"   # "nothing" is allowed
    report = eg.evaluate_github("applicant0001", PROFILE_A, llm_factory=lambda: FakeLLM(_answer(3)))
    assert _by_skill(report)["python"].observed_level == 3


def test_bad_json_gets_a_correction_round():
    llm = FakeLLM("not json", _answer(3))
    report = eg.evaluate_github("applicant0001", PROFILE_A, llm_factory=lambda: llm)
    assert report.trace.llm_calls == 2 and _by_skill(report)["python"].method == "llm"
    assert "<github_evidence>" not in llm.prompts[1]      # correction does not resend evidence


def test_missing_gateway_falls_back_to_rules():
    report = eg.evaluate_github("applicant0001", PROFILE_A)
    assert report.mode == "rules"
    assert "LLM_GATEWAY_URL" in (report.trace.llm_error or "")
    assert _by_skill(report)["python"].status == "partially_verified"


def test_it_runs_after_the_profile_agent_and_matches_its_id():
    with pytest.raises(eg.EvidenceValidationError, match="required"):
        eg.evaluate_github("applicant0001", None)
    with pytest.raises(eg.EvidenceValidationError, match="applicant0999"):
        eg.evaluate_github("applicant0001", {**PROFILE_A, "applicant_id": "applicant0999"})


def test_payload_fits_resolve_profile_and_keeps_the_trail():
    payload = eg.evaluate_github("applicant0001", PROFILE_A,
                                 llm_factory=lambda: FakeLLM(_answer(3))).payload()
    assert payload["applicant_id"] == "applicant0001"
    for v in payload["skill_verification"]:
        assert {"canonical_skill", "github_observed_level", "verification_status",
                "method", "rule_observed_level", "notes"} <= set(v)


def test_prompt_carries_the_shared_scale_verbatim():
    block = proficiency_taxonomy()
    assert "PROFICIENCY SCALE (1-3)" in block and "Tie-break: When the evidence is ambiguous" in block
    assert "Did the applicant make the structural decisions" in block


def test_every_skill_is_a_taxonomy_id():
    assert to_skill_id("Amazon Web Services") == "aws"
    assert to_skill_id("Unreal Engine") is None
    profile = from_profile_payload({"applicant_id": "a", "skills": [
        {"canonical_skill": "postgres", "claimed_level": 1},
        {"canonical_skill": "PostgreSQL", "claimed_level": 3}]})
    assert [(c.skill_id, c.level) for c in profile.skills] == [("postgresql", 3)]


def test_payload_is_keyed_by_the_profile_agents_own_names():
    """resolve_profile joins on canonical_skill; C must echo A's exact strings back."""
    profile = {"applicant_id": "applicant0001", "skills": [
        {"canonical_skill": "Python", "claimed_level": 2},
        {"canonical_skill": "Postgres", "claimed_level": 1},
        {"canonical_skill": "PostgreSQL", "claimed_level": 3}]}
    payload = eg.evaluate_github("applicant0001", profile, use_llm=False).payload()
    rows = {v["canonical_skill"]: v for v in payload["skill_verification"]}
    assert set(rows) == {"Python", "Postgres", "PostgreSQL"}
    assert rows["Python"]["skill_id"] == "python"
    assert rows["Postgres"]["claimed_level"] == 1 and rows["PostgreSQL"]["claimed_level"] == 3


def test_rules_doc_matches_the_code():
    """A rule change rewrites RULES.md; fail once so the new text gets reviewed and committed."""
    from src.evidence_agent.rules import RULES_PATH, sync_rules_doc

    assert not sync_rules_doc(), f"{RULES_PATH.name} was out of date and has been rewritten"
