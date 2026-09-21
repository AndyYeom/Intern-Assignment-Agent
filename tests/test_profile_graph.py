from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from src.profile_agent import profile_graph
from src.profile_agent.profile_graph import (
    ApplicantProfile,
    ApplicantSkill,
    SkillEvidence,
    ProfileConfigurationError,
    ProfileValidationError,
    ApplicantEvaluationError,
    evaluate_resume,
    write_json_atomic,
)


VALID_JSON = {
    "applicant_id": "APP-001",
    "skills": [
        {
            "canonical_skill": "Python",
            "category": "Programming Languages",
            "claimed_level": 2,
            "confidence": 0.85,
            "evidence": [
                {
                    "source": "resume",
                    "text": "Built ETL pipelines in Python for internal reporting.",
                    "page": None,
                }
            ],
            "reasoning": "The resume describes independent Python data pipeline work.",
        }
    ],
    "domains": ["Data Engineering"],
    "interests": ["Analytics"],
    "education": [],
    "work_experience": [],
}


class FakeLLM:
    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or [json.dumps(VALID_JSON)]
        self.calls = 0

    def invoke(self, message: Any):
        self.calls += 1
        if self.calls > len(self.responses):
            return AIMessage(content=self.responses[-1])
        return AIMessage(content=self.responses[self.calls - 1])


def make_resume_path(tmp_path: Path) -> Path:
    path = tmp_path / "resume.pdf"
    path.write_bytes(b"%PDF-1.4\nnot-a-real-pdf")
    return path


def make_portfolio_path(tmp_path: Path, suffix: str) -> Path:
    path = tmp_path / f"portfolio{suffix}"
    path.write_text("Portfolio content", encoding="utf-8")
    return path


def test_resume_only_workflow(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python, SQL, AWS")

    result = profile_graph.evaluate_resume(
        resume_path=resume_path,
        applicant_id="APP-001",
        llm_factory=lambda: FakeLLM(),
    )

    assert result.applicant_id == "APP-001"
    assert result.skills[0].canonical_skill == "Python"


def test_resume_with_pdf_portfolio(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    portfolio_path = make_portfolio_path(tmp_path, ".pdf")

    def fake_extract(pdf: str, output_path: str | None = None, enable_ocr: bool = False) -> str:
        if Path(pdf) == resume_path:
            return "Python, ETL, AWS"
        assert Path(pdf) == portfolio_path
        assert enable_ocr is False
        return "Built a dashboard in PostgreSQL and Tableau."

    monkeypatch.setattr(profile_graph, "extract_resume", fake_extract)

    graph = profile_graph.profile_graph
    state = {"resume_path": str(resume_path), "applicant_id": "APP-001", "portfolio_path": str(portfolio_path), "llm_factory": lambda: FakeLLM()}
    result = graph.invoke(state)
    assert result["profile"].applicant_id == "APP-001"


def test_resume_with_markdown_portfolio(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    portfolio_path = make_portfolio_path(tmp_path, ".md")
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Built backend services in Python")
    state = {"resume_path": str(resume_path), "applicant_id": "APP-001", "portfolio_path": str(portfolio_path), "llm_factory": lambda: FakeLLM()}
    result = profile_graph.profile_graph.invoke(state)
    assert result["profile"].applicant_id == "APP-001"


def test_resume_with_text_portfolio(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    portfolio_path = make_portfolio_path(tmp_path, ".txt")
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Mentored teams and wrote Python scripts")
    state = {"resume_path": str(resume_path), "applicant_id": "APP-001", "portfolio_path": str(portfolio_path), "llm_factory": lambda: FakeLLM()}
    result = profile_graph.profile_graph.invoke(state)
    assert result["profile"].applicant_id == "APP-001"


def test_ocr_flag_forwarded_to_extractor(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    captured = {}

    def fake_extract(pdf: str, output_path: str | None = None, enable_ocr: bool = False) -> str:
        captured["enable_ocr"] = enable_ocr
        return "Skill evidence"

    monkeypatch.setattr(profile_graph, "extract_resume", fake_extract)
    profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", enable_ocr=True, llm_factory=lambda: FakeLLM())
    assert captured["enable_ocr"] is True


def test_unsupported_portfolio_extension(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    portfolio = tmp_path / "portfolio.csv"
    portfolio.write_text("bad")
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")
    with pytest.raises(ProfileValidationError, match="Unsupported portfolio format"):
        profile_graph.extract_documents({"resume_path": str(resume_path), "portfolio_path": str(portfolio), "applicant_id": "APP-001"})


def test_empty_resume_extraction(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "   \n \t ")
    with pytest.raises(ProfileValidationError, match="empty|whitespace"):
        profile_graph.extract_documents({"resume_path": str(resume_path), "applicant_id": "APP-001"})


def test_state_passed_from_extraction_to_evaluation(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python backend work")
    state = {"resume_path": str(resume_path), "applicant_id": "APP-001", "llm_factory": lambda: FakeLLM()}
    result = profile_graph.profile_graph.invoke(state)
    assert result["resume_text"]
    assert result["profile"].applicant_id == "APP-001"


def test_valid_json_parsed_into_applicant_profile(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python, SQL")
    profile = profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: FakeLLM())
    assert isinstance(profile, ApplicantProfile)
    assert profile.skills[0].canonical_skill == "Python"


def test_markdown_fence_json_is_corrected(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")

    class FixingLLM(FakeLLM):
        def __init__(self):
            super().__init__(["```json\n{\"applicant_id\": \"APP-001\", \"skills\": []}\n```", json.dumps(VALID_JSON)])

    result = profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: FixingLLM())
    assert result.applicant_id == "APP-001"


def test_invalid_proficiency_level_is_rejected(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")

    invalid = {**VALID_JSON, "skills": [{**VALID_JSON["skills"][0], "claimed_level": 5}]}
    llm = FakeLLM([json.dumps(invalid), json.dumps(VALID_JSON)])
    result = profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: llm)
    assert result.skills[0].canonical_skill == "Python"


def test_confidence_outside_range_rejected(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")

    invalid = {**VALID_JSON, "skills": [{**VALID_JSON["skills"][0], "confidence": 1.5}]}
    llm = FakeLLM([json.dumps(invalid), json.dumps(VALID_JSON)])
    result = profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: llm)
    assert result.skills[0].confidence == 0.85


def test_scored_skill_without_evidence_is_rejected(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")

    invalid = {**VALID_JSON, "skills": [{**VALID_JSON["skills"][0], "evidence": []}]}
    llm = FakeLLM([json.dumps(invalid), json.dumps(VALID_JSON)])
    result = profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: llm)
    assert len(result.skills) == 1


def test_missing_required_environment_variables(monkeypatch):
    for key in ["LLM_GATEWAY_URL", "LLM_GATEWAY_API_KEY", "LLM_MODEL"]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ProfileConfigurationError, match="LLM_GATEWAY_URL|LLM_GATEWAY_API_KEY|LLM_MODEL"):
        profile_graph.create_profile_llm()


def test_model_factory_uses_gateway_url_api_key_and_model_id(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "https://api.softwaresystems.app")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_MODEL", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")
    model = profile_graph.create_profile_llm()
    assert model.model == "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert model.base_url == "https://api.softwaresystems.app"
    assert model.client_kwargs["headers"]["X-API-Key"] == "secret-key"


def test_correction_retry_succeeds_after_one_invalid_response(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")

    bad = {**VALID_JSON, "skills": [{**VALID_JSON["skills"][0], "claimed_level": 4}]}
    llm = FakeLLM([json.dumps(bad), json.dumps(VALID_JSON)])
    profile = profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: llm)
    assert profile.applicant_id == "APP-001"
    assert llm.calls == 2


def test_correction_retry_raises_after_max_attempts(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")

    bad = {**VALID_JSON, "skills": [{**VALID_JSON["skills"][0], "claimed_level": 4}]}
    llm = FakeLLM([json.dumps(bad), json.dumps(bad), json.dumps(bad), json.dumps(bad)])
    with pytest.raises(ApplicantEvaluationError, match="failed validation|JSON"):
        profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: llm)


def test_authentication_failures_are_not_retried(tmp_path, monkeypatch):
    resume_path = make_resume_path(tmp_path)
    monkeypatch.setattr(profile_graph, "extract_resume", lambda *args, **kwargs: "Python")

    class AuthLLM(FakeLLM):
        def invoke(self, message: Any):
            raise httpx.HTTPStatusError("unauthorized", request=httpx.Request("POST", "https://example.com"), response=httpx.Response(401))

    with pytest.raises(ApplicantEvaluationError, match="authentication|401|403"):
        profile_graph.evaluate_resume(resume_path=resume_path, applicant_id="APP-001", llm_factory=lambda: AuthLLM())


def test_atomic_json_output(tmp_path):
    target = tmp_path / "profile.json"
    write_json_atomic(target, '{"k": 1}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_cli_writes_json_to_stdout_when_no_output_path(monkeypatch, capsys, tmp_path):
    resume_path = make_resume_path(tmp_path)

    def fake_evaluate(**kwargs):
        return ApplicantProfile(**VALID_JSON)

    monkeypatch.setattr(profile_graph, "evaluate_resume", fake_evaluate)
    code = profile_graph.main([str(resume_path), "--applicant-id", "APP-001"])
    captured = capsys.readouterr()
    assert code == 0
    assert "\"applicant_id\": \"APP-001\"" in captured.out


def test_main_requires_pdf_resume(tmp_path):
    bad = tmp_path / "resume.txt"
    bad.write_text("oops")
    assert profile_graph.main([str(bad), "--applicant-id", "APP-001"]) == 1
