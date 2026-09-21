"""Profile agent (A) then evidence agent (C) on one applicant, against the real gateway.

This spends real tokens, so it never runs in the normal suite: the file name
does not match pytest's test_*.py pattern, and it also skips unless asked:

    RUN_LLM_INTEGRATION=1 uv run pytest tests/test-A-C-integration.py -s

Each agent gets a hard budget of model calls; a third call fails the test
instead of billing. Outputs land in output/integration/ for inspection.

A's profile is saved as soon as A finishes and reused on the next run, so a
failure in C never pays for A twice. Set RERUN_A=1 to call A again.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from generator.github.skill_map import skill_ids

APPLICANT = os.getenv("INTEGRATION_APPLICANT", "applicant0016")   # carries a planted exaggeration
MAX_CALLS_PER_AGENT = 2
OUT = Path("output/integration")

pytestmark = [
    pytest.mark.skipif(os.getenv("RUN_LLM_INTEGRATION") != "1",
                       reason="spends real tokens; set RUN_LLM_INTEGRATION=1 to run"),
    pytest.mark.real_data,   # reads the real GitHub profiles; writes only output/integration/
]


class BudgetedLLM:
    """Wraps a chat model: counts calls and tokens, refuses to exceed the budget."""

    def __init__(self, llm: Any, name: str, max_calls: int = MAX_CALLS_PER_AGENT):
        self.llm, self.name, self.max_calls = llm, name, max_calls
        self.calls = self.input_tokens = self.output_tokens = 0
        self.model = getattr(llm, "model", None)

    def invoke(self, prompt: Any) -> Any:
        if self.calls >= self.max_calls:
            raise RuntimeError(f"{self.name}: budget of {self.max_calls} model calls exhausted")
        self.calls += 1
        message = self.llm.invoke(prompt)
        usage = getattr(message, "usage_metadata", None) or {}
        self.input_tokens += int(usage.get("input_tokens", 0) or 0)
        self.output_tokens += int(usage.get("output_tokens", 0) or 0)
        return message

    def summary(self) -> str:
        return (f"{self.name}: {self.calls} call(s), {self.input_tokens} tokens in, "
                f"{self.output_tokens} tokens out")


def _show_a(profile: Any) -> None:
    print(f"\n=== A: profile agent ({len(profile.skills)} skills) ===")
    for s in profile.skills:
        quote = s.evidence[0].text if s.evidence else ""
        print(f"  {s.canonical_skill:<28} level {s.claimed_level}  conf {s.confidence:.2f}")
        print(f"      quote:  {quote[:110]}")
        print(f"      reason: {s.reasoning[:110]}")
    if profile.domains or profile.interests:
        print(f"  domains: {profile.domains}  interests: {profile.interests}")


def _show_c(report: Any) -> None:
    t = report.trace
    print(f"\n=== C: evidence agent (mode {report.mode}, tier {report.profile_tier}) ===")
    print(f"  model: {t.model}  calls {t.llm_calls}  tokens {t.input_tokens} in / "
          f"{t.output_tokens} out  error: {t.llm_error}")
    print(f"  needing model: {t.skills_needing_model}  sent: {t.skills_sent_to_model}")
    print(f"  unmapped from A: {report.unmapped_claims}")
    for s in report.skills:
        names = ", ".join(s.source_names) or s.skill_id
        print(f"  {s.skill_id:<16} ({names})  claimed {s.claimed_level} -> observed "
              f"{s.observed_level} (rules {s.rule_observed_level})  {s.status}  "
              f"[{s.method}, {s.evidence_strength}]")
        print(f"      {s.rationale[:130]}")
        for link in s.repo_links[:3]:
            print(f"      - {link}")
        for note in s.notes:
            print(f"      note: {note[:130]}")
    if report.unclaimed_observed:
        extra = ", ".join(f"{o.skill_id}={o.observed_level}" for o in report.unclaimed_observed)
        print(f"  on GitHub but not claimed: {extra}")


def test_profile_agent_then_evidence_agent():
    from src.evidence_agent import create_evidence_llm, evaluate_github
    from src.evidence_agent.evidence_graph import write_json_atomic
    from src.profile_agent import ApplicantProfile, create_profile_llm, evaluate_resume

    pdf = Path(f"data/resumes/rendered/{APPLICANT}.pdf")
    assert pdf.is_file(), pdf

    # A: resume PDF -> claimed skills. Reused from the last run unless RERUN_A=1.
    saved_a = OUT / f"{APPLICANT}.A.json"
    if saved_a.is_file() and os.getenv("RERUN_A") != "1":
        profile = ApplicantProfile.model_validate_json(saved_a.read_text(encoding="utf-8"))
        print(f"\nA: reused {saved_a} (0 tokens; RERUN_A=1 to call A again)")
    else:
        budget_a = BudgetedLLM(create_profile_llm(), "A")
        profile = evaluate_resume(pdf, applicant_id=APPLICANT, llm_factory=lambda: budget_a)
        write_json_atomic(saved_a, profile)
        print("\n" + budget_a.summary())
    assert profile.applicant_id == APPLICANT
    assert profile.skills, "the profile agent found no skills"
    _show_a(profile)

    # C: A's claims -> GitHub verification, after A as in the real workflow.
    budget_c = BudgetedLLM(create_evidence_llm(), "C")
    report = evaluate_github(APPLICANT, profile, llm_factory=lambda: budget_c)
    write_json_atomic(OUT / f"{APPLICANT}.C.json", report)
    print(budget_c.summary())
    _show_c(report)

    payload = report.payload()
    (OUT / f"{APPLICANT}.C.payload.json").write_text(json.dumps(payload, indent=2) + "\n")
    assert payload["applicant_id"] == profile.applicant_id
    assert {v["skill_id"] for v in payload["skill_verification"]} <= skill_ids()
    a_names = {s.canonical_skill for s in profile.skills}
    assert {v["canonical_skill"] for v in payload["skill_verification"]} <= a_names
    assert report.trace.llm_error is None or not report.trace.skills_sent_to_model, \
        f"C fell back to rules: {report.trace.llm_error}"
