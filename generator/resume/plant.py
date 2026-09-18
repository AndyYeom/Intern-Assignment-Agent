"""Plant deliberate exaggerations into 10 resumes, and keep the answer key.

Two kinds, alternating:

  inflated     a skill the person really used, but thinly (fewest commits),
               now claimed as Advanced
  unsupported  a skill with no GitHub evidence at all, claimed as Advanced

Choice uses only the collector's raw skill evidence, never the evidence
agent's judgement, so the agent is not graded against its own rules. The
answer key lives in data/eval/, not in applicants.csv, which the agent reads.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from generator.config import DATA
from generator.github.skill_map import taxonomy
from generator.resume import generate
from generator.resume.schema import GenRequest
from generator.schemas import GitHubProfile

EVAL_DIR = DATA / "eval"
ANSWER_KEY = EVAL_DIR / "planted_exaggerations.json"
PLANT_COUNT = 10
SALT = "plant-v1"
# Skills GitHub could show if they were real: an unsupported claim is testable.
UNSUPPORTED_POOL = ["kubernetes", "docker", "aws", "graphql", "redis", "deep-learning",
                    "cicd", "postgresql", "react", "go"]


def _skill(skill_id: str) -> dict[str, Any]:
    return next(s for s in taxonomy()["skills"] if s["id"] == skill_id)


def _pick(profile: GitHubProfile, kind: str, rotation: int = 0) -> str | None:
    evidenced = {e.skill_id for e in profile.skill_evidence}
    if kind == "unsupported":
        free = [s for s in UNSUPPORTED_POOL if s not in evidenced]
        return free[rotation % len(free)] if free else None
    thin = [e for e in profile.skill_evidence
            if {"language", "manifest"} & set(e.sources) and e.commit_count > 0]
    thin.sort(key=lambda e: (e.commit_count, e.skill_id))
    return thin[0].skill_id if thin else None


def _claim(spec: dict[str, Any], skill_id: str) -> str:
    skill = _skill(skill_id)
    names = {skill["name"].lower(), skill_id, *(a.lower() for a in skill.get("aliases", []))}
    skills = spec.setdefault("skills", {}) or {}
    for category, items in skills.items():
        skills[category] = [i for i in items if i.strip().lower() not in names]
    text = f"{skill['name']} (Advanced)"
    skills.setdefault(skill["category"], []).append(text)
    spec["skills"] = {k: v for k, v in skills.items() if v}
    return text


def plant(applicant_ids: list[str]) -> list[dict[str, Any]]:
    if ANSWER_KEY.exists():
        return json.loads(ANSWER_KEY.read_text(encoding="utf-8"))
    order = sorted(applicant_ids, key=lambda a: hashlib.sha256(f"{SALT}:{a}".encode()).hexdigest())
    key: list[dict[str, Any]] = []
    for applicant_id in order:
        if len(key) == PLANT_COUNT:
            break
        kind = "inflated" if len(key) % 2 == 0 else "unsupported"
        profile = GitHubProfile.model_validate_json(
            (DATA / "githubs" / "profiles" / f"{applicant_id}.json").read_text(encoding="utf-8"))
        skill_id = _pick(profile, kind, rotation=len(key) // 2)
        if skill_id is None:
            continue
        spec_file = generate.spec_path(applicant_id)
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        text = _claim(spec, skill_id)
        generate.generate(GenRequest.model_validate(spec))
        key.append({"applicant_id": applicant_id, "skill_id": skill_id, "kind": kind,
                    "claimed_level": 3, "resume_text": text})
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    ANSWER_KEY.write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    return key
