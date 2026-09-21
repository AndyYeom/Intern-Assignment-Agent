"""Evidence agent: verifies the profile agent's claims against GitHub.

Runs after the profile agent, and is called the same way:

    profile  = evaluate_resume(resume_pdf, applicant_id=...)     # agent A
    evidence = evaluate_github(applicant_id, profile)            # agent C

Graph: load_inputs -> assess_rules -> verify_with_llm -> reconcile -> END

  assess_rules     reads every claim deterministically (verify.py) and settles
                   the ones that need no judgment: a claim GitHub already meets,
                   or a skill no repository touches.
  verify_with_llm  sends only the rest, with only the repositories behind them,
                   to an Ollama model through the LLM gateway, with the shared
                   proficiency scale in the prompt. Nothing left: no call.
  reconcile        the model proposes, the rules bound it: a verdict must cite
                   real repositories and stay within one level of the rules'
                   reading, or that skill falls back to the rules. A missing or
                   failing gateway falls back entirely.

Every verdict keeps the rules' reading beside the final one, says which method
decided it and why, and the report's `trace` records what the model saw and
what it cost. Gateway settings are the profile agent's: LLM_GATEWAY_URL,
LLM_GATEWAY_API_KEY, LLM_MODEL.

    python -m src.evidence_agent.evidence_graph applicant0001 --profile a.json --payload
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

import httpx
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from generator.config import PROFILES_DIR
from generator.schemas import GitHubProfile, RepoRecord
from src.evidence_agent.claims import from_profile_payload
from src.evidence_agent.evidence_models import (
    ApplicantProfile,
    EvidenceReport,
    EvidenceTrace,
    LLMEvidenceOutput,
    LLMSkillVerdict,
    SkillVerification,
    Status,
)
from src.evidence_agent.evidence_prompts import (
    build_correction_prompt,
    build_evidence_prompt,
)
from src.evidence_agent.verify import verify


class EvidenceConfigurationError(RuntimeError):
    """Raised when the gateway environment is missing required configuration."""


class EvidenceValidationError(ValueError):
    """Raised when input data fails validation: missing profile, mismatched applicant."""


class EvidenceEvaluationError(RuntimeError):
    """Raised when the gateway or model output cannot be used."""


load_dotenv(dotenv_path=Path(".env"), override=False)

MAX_LEVEL_SHIFT = 1          # how far the model may move from the rules' level
UNSEEN_LEVEL_CAP = 2         # a level the rules found no repository for stays at most here
README_CHARS = 300
COMMIT_MESSAGES = 5

# Hand-written instead of the parser's JSON Schema: a third of the tokens, same checks.
FORMAT_INSTRUCTIONS = """{"applicant_id": "<as given>", "skills": [{"skill_id": "<a skill_id from CLAIMS>", \
"observed_level": 1 | 2 | 3 | null, "evidence_strength": "none" | "weak" | "moderate" | "strong", \
"repo_links": ["<a url from GITHUB_EVIDENCE>"], "rationale": "<one or two sentences>"}]}"""


def _gateway_settings() -> tuple[str, str, str]:
    values = {name: (os.getenv(name) or "").strip()
              for name in ("LLM_GATEWAY_URL", "LLM_GATEWAY_API_KEY", "LLM_MODEL")}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise EvidenceConfigurationError(
            "Missing required gateway configuration: " + ", ".join(missing))
    return values["LLM_GATEWAY_URL"], values["LLM_GATEWAY_API_KEY"], values["LLM_MODEL"]


def create_evidence_llm() -> Any:
    from langchain_ollama import ChatOllama

    gateway_url, gateway_api_key, llm_model = _gateway_settings()
    return ChatOllama(model=llm_model, base_url=gateway_url, temperature=0.0,
                      num_predict=1000,
                      client_kwargs={"headers": {"X-API-Key": gateway_api_key}})


class EvidenceGraphState(TypedDict, total=False):
    applicant_id: str
    profile: dict[str, Any]             # agent A's ApplicantProfile
    use_llm: bool
    llm_factory: Callable[[], Any]
    github: GitHubProfile
    claims: ApplicantProfile
    rule_report: EvidenceReport
    to_judge: list[str]                 # skill ids the rules could not settle
    llm_output: LLMEvidenceOutput | None
    trace: EvidenceTrace
    report: EvidenceReport


# ---- which claims need a model at all ------------------------------------------

def settled_by_rules(rule: SkillVerification) -> str | None:
    """Why the rules' verdict stands without a model, or None if it needs judgment.

    A model can only confirm a claim GitHub already meets, and has nothing to read
    for a skill no repository touches, so neither is worth a call.
    """
    if rule.status == "verified":
        return f"GitHub already supports the claim (rules read level {rule.observed_level})"
    if rule.status == "not_observed" and rule.evidence_strength == "none":
        return "no repository shows this skill"
    return None


# ---- nodes ----------------------------------------------------------------------

def load_inputs(state: EvidenceGraphState) -> dict[str, Any]:
    applicant_id = (state.get("applicant_id") or "").strip()
    if not applicant_id:
        raise EvidenceValidationError("An applicant_id is required.")
    profile = state.get("profile")
    if not profile:
        raise EvidenceValidationError(
            "The profile agent's output is required: the evidence agent verifies its claims.")
    if profile.get("applicant_id") != applicant_id:
        raise EvidenceValidationError(
            f"Profile is for {profile.get('applicant_id')!r}, expected {applicant_id!r}")
    path = PROFILES_DIR / f"{applicant_id}.json"
    if not path.is_file():
        raise EvidenceValidationError(f"No GitHub profile for {applicant_id}: {path}")
    github = GitHubProfile.model_validate_json(path.read_text(encoding="utf-8"))
    return {"github": github, "claims": from_profile_payload(profile)}


def assess_rules(state: EvidenceGraphState) -> dict[str, Any]:
    report = verify(state["claims"], state["github"])
    settled = {s.skill_id: why for s in report.skills if (why := settled_by_rules(s))}
    to_judge = [s.skill_id for s in report.skills if s.skill_id not in settled]
    return {"rule_report": report, "to_judge": to_judge,
            "trace": EvidenceTrace(skills_decided_by_rules=settled,
                                   skills_needing_model=to_judge)}


def verify_with_llm(state: EvidenceGraphState) -> dict[str, Any]:
    trace = state["trace"].model_copy()
    if not state["to_judge"]:
        return {"llm_output": None, "trace": trace}
    if not state.get("use_llm", True):
        trace.llm_error = "model disabled; rules only"
        return {"llm_output": None, "trace": trace}
    try:
        factory = state.get("llm_factory") or create_evidence_llm
        output = _ask_model(factory(), state, trace)
    except (EvidenceConfigurationError, EvidenceEvaluationError) as exc:
        trace.llm_error = str(exc)
        return {"llm_output": None, "trace": trace}
    return {"llm_output": output, "trace": trace}


def reconcile_node(state: EvidenceGraphState) -> dict[str, Any]:
    return {"report": reconcile(state["rule_report"], state.get("llm_output"),
                                state["github"], state["trace"])}


def _build_graph() -> StateGraph:
    builder = StateGraph(EvidenceGraphState)
    builder.add_node("load_inputs", load_inputs)
    builder.add_node("assess_rules", assess_rules)
    builder.add_node("verify_with_llm", verify_with_llm)
    builder.add_node("reconcile", reconcile_node)
    builder.add_edge(START, "load_inputs")
    builder.add_edge("load_inputs", "assess_rules")
    builder.add_edge("assess_rules", "verify_with_llm")
    builder.add_edge("verify_with_llm", "reconcile")
    builder.add_edge("reconcile", END)
    return builder


evidence_graph = _build_graph().compile()


def evaluate_github(applicant_id: str, profile: Any, *, use_llm: bool = True,
                    llm_factory: Callable[[], Any] | None = None) -> EvidenceReport:
    """Verify one applicant's profile-agent claims. `profile` is A's ApplicantProfile."""
    data = profile.model_dump() if hasattr(profile, "model_dump") else profile
    state: EvidenceGraphState = {"applicant_id": applicant_id, "profile": data,
                                 "use_llm": use_llm}
    if llm_factory is not None:
        state["llm_factory"] = llm_factory
    return evidence_graph.invoke(state)["report"]


# ---- what the model sees: only what the open claims need ------------------------

def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _repos_for(github: GitHubProfile, skill_ids: set[str]) -> list[RepoRecord]:
    return [r for r in github.repos
            if any(s.get("skill_id") in skill_ids for s in r.skill_signals)]


def _repo_evidence(repo: RepoRecord, skill_ids: set[str]) -> dict[str, Any]:
    total = sum(repo.languages.values()) or 1
    structure = repo.structure
    kinds = repo.judgment.get("commit_message_kinds", {})
    item = {
        "url": repo.html_url,
        "about": repo.description,
        "lang": {k: round(v / total, 2) for k, v in
                 sorted(repo.languages.items(), key=lambda kv: -kv[1])[:3]},
        "skill_signals": sorted({s["detail"] for s in repo.skill_signals
                                 if s.get("skill_id") in skill_ids})[:4],
        "commits": {k: repo.commits.get(k) for k in ("count", "active_days", "span_days")},
        "share": repo.contribution_share,
        "msgs": (repo.commits.get("messages_sample") or [])[:COMMIT_MESSAGES],
        "entry": [k for k, v in structure.get("entry_flags", {}).items() if v],
        "intermediate": [k for k, v in structure.get("intermediate_flags", {}).items() if v],
        "judgment": {k: v for k, v in kinds.items() if v},
        "others_depend": repo.judgment.get("others_depend") or None,
        "fork": repo.is_fork or None,
        "readme": (repo.readme_excerpt or "")[:README_CHARS] or None,
    }
    return {k: v for k, v in item.items() if v not in (None, [], {}, "")}


def _prompt_parts(state: EvidenceGraphState) -> tuple[str, str, str, list[str]]:
    open_ids = set(state["to_judge"])
    claims = [c for c in state["claims"].skills if c.skill_id in open_ids]
    rules = [s for s in state["rule_report"].skills if s.skill_id in open_ids]
    repos = _repos_for(state["github"], open_ids)
    claims_text = _compact([{"skill_id": c.skill_id, "claimed_level": c.level,
                             "resume": c.evidence_quote} for c in claims])
    rules_text = _compact([{"skill_id": s.skill_id, "observed_level": s.observed_level,
                            "strength": s.evidence_strength,
                            "why": [r for repo in s.repos for r in repo.reasons[:1]]}
                           for s in rules])
    github_text = _compact([_repo_evidence(r, open_ids) for r in repos])
    return claims_text, rules_text, github_text, [r.html_url for r in repos]


def _text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def _clean_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def _is_transient(exc: BaseException) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in {401, 403, 413}:
        return False
    return (isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
            or (status is not None and (status >= 500 or status in {408, 429})))


def _invoke(llm: Any, prompt: Any, trace: EvidenceTrace, *, max_attempts: int = 3) -> str:
    trace.prompt_chars += len(str(prompt))
    for attempt in range(1, max_attempts + 1):
        try:
            message = llm.invoke(prompt)
        except Exception as exc:
            if not _is_transient(exc) or attempt == max_attempts:
                raise EvidenceEvaluationError(
                    f"Gateway request failed: {type(exc).__name__}: {exc}") from exc
            time.sleep(0.25 * attempt)
            continue
        trace.llm_calls += 1
        usage = getattr(message, "usage_metadata", None) or {}
        trace.input_tokens += int(usage.get("input_tokens", 0) or 0)
        trace.output_tokens += int(usage.get("output_tokens", 0) or 0)
        return _text(message)
    raise EvidenceEvaluationError("Gateway request failed.")


def _ask_model(llm: Any, state: EvidenceGraphState, trace: EvidenceTrace) -> LLMEvidenceOutput:
    applicant_id = state["applicant_id"]
    claims, rules, github, repo_urls = _prompt_parts(state)
    trace.model = getattr(llm, "model", None) or type(llm).__name__
    trace.skills_sent_to_model = list(state["to_judge"])
    trace.repos_sent_to_model = repo_urls
    raw = _invoke(llm, build_evidence_prompt(applicant_id, claims, rules, github,
                                             FORMAT_INSTRUCTIONS), trace)
    for attempt in range(3):
        try:
            output = LLMEvidenceOutput.model_validate_json(_clean_json_text(raw))
            if output.applicant_id != applicant_id:
                raise ValueError(f"applicant_id must be {applicant_id}")
            return output
        except ValueError as exc:
            if attempt == 2:
                raise EvidenceEvaluationError(
                    f"Model output failed validation after retries: {exc}") from exc
            # The correction prompt carries only the claims, not the evidence again.
            raw = _invoke(llm, build_correction_prompt(
                applicant_id, claims, raw, str(exc)[:500], FORMAT_INSTRUCTIONS), trace)
    raise EvidenceEvaluationError("Model output failed validation.")


# ---- reconcile: the model proposes, the rules bound it ----------------------------

def _status(claimed: int, observed: int | None) -> Status:
    if observed is None:
        return "not_observed"
    gap = claimed - observed
    return "verified" if gap <= 0 else "partially_verified" if gap == 1 else "conflicting"


def _accept(rule: SkillVerification, verdict: LLMSkillVerdict,
            real_urls: set[str]) -> SkillVerification | str:
    """The model's verdict, bounded by the rules; or the reason it is rejected."""
    links = [u.rstrip("/") for u in verdict.repo_links if u.rstrip("/") in real_urls]
    level, notes = verdict.observed_level, []
    if level is not None and not links:
        return "model verdict rejected: it cited no repository from the evidence"
    if level is not None and rule.observed_level is not None:
        low, high = rule.observed_level - MAX_LEVEL_SHIFT, rule.observed_level + MAX_LEVEL_SHIFT
        if not low <= level <= high:
            notes.append(f"model level {level} bounded to within {MAX_LEVEL_SHIFT} of the rules")
            level = min(max(level, low), high)
    elif level is not None and level > UNSEEN_LEVEL_CAP:
        notes.append(f"rules found no repository; model level {level} capped")
        level = UNSEEN_LEVEL_CAP
    if level != rule.observed_level:
        notes.append(f"model changed the rules' level {rule.observed_level} to {level}")
    return rule.model_copy(update={
        "status": _status(rule.claimed_level, level),
        "observed_level": level,
        "evidence_strength": ("none" if level is None else
                              "weak" if verdict.evidence_strength == "none" else
                              verdict.evidence_strength),
        "repo_links": links if level is not None else [],
        "repos": [r for r in rule.repos if r.html_url in links],
        "rationale": verdict.rationale,
        "method": "llm",
        "notes": notes,
    })


def reconcile(rule_report: EvidenceReport, llm_output: LLMEvidenceOutput | None,
              github: GitHubProfile, trace: EvidenceTrace | None = None) -> EvidenceReport:
    trace = trace or EvidenceTrace()
    verdicts = {v.skill_id: v for v in (llm_output.skills if llm_output else [])}
    real_urls = {r.html_url.rstrip("/") for r in github.repos}
    skills = []
    for rule in rule_report.skills:
        base = rule.model_copy(update={"rule_observed_level": rule.observed_level,
                                       "rule_status": rule.status, "method": "rules"})
        if rule.skill_id in trace.skills_decided_by_rules:
            skills.append(base.model_copy(update={
                "notes": [f"decided by rules: {trace.skills_decided_by_rules[rule.skill_id]}"]}))
            continue
        verdict = verdicts.get(rule.skill_id)
        if verdict is None:
            reason = trace.llm_error or "model returned no verdict for this skill"
            skills.append(base.model_copy(update={"notes": [f"rules fallback: {reason}"]}))
            continue
        accepted = _accept(base, verdict, real_urls)
        skills.append(base.model_copy(update={"notes": [accepted]})
                      if isinstance(accepted, str) else accepted)

    methods = {s.method for s in skills}
    mode = "rules" if methods <= {"rules"} else "llm" if methods == {"llm"} else "mixed"
    return rule_report.model_copy(update={
        "skills": skills,
        "status_counts": dict(sorted(Counter(s.status for s in skills).items())),
        "mode": mode,
        "trace": trace,
    })


# ---- output ---------------------------------------------------------------------

def write_json_atomic(target_path: str | Path, payload: Any) -> None:
    destination = Path(target_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump_json"):
        text = payload.model_dump_json(indent=2)
    elif isinstance(payload, dict):
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        text = str(payload)
    handle, temp_path = tempfile.mkstemp(dir=str(destination.parent),
                                         prefix=f".{destination.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as write_handle:
            write_handle.write(text)
            write_handle.write("\n")
        os.replace(temp_path, destination)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    from src.evidence_agent.rules import sync_rules_doc

    sync_rules_doc()
    parser = argparse.ArgumentParser(
        description="Verify the profile agent's skill claims against GitHub.")
    parser.add_argument("applicant_id", help="e.g. applicant0001")
    parser.add_argument("--profile", required=True,
                        help="the profile agent's JSON for this applicant")
    parser.add_argument("--rules-only", action="store_true", help="skip the model")
    parser.add_argument("--output", help="optional output JSON path")
    parser.add_argument("--payload", action="store_true",
                        help="the orchestrator payload instead of the full report")
    args = parser.parse_args(argv)

    try:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        report = evaluate_github(args.applicant_id, profile, use_llm=not args.rules_only)
        out: Any = report.payload() if args.payload else report
        if args.output:
            write_json_atomic(args.output, out)
            print(f"Wrote evidence to {args.output} (mode: {report.mode})", file=sys.stderr)
        else:
            print(json.dumps(out, indent=2) if isinstance(out, dict)
                  else out.model_dump_json(indent=2))
        if report.trace.llm_error:
            print(f"note: {report.trace.llm_error}", file=sys.stderr)
        return 0
    except (EvidenceValidationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
