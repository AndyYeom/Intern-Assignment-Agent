"""Where claims come from.

The real input is the profile agent's `ApplicantProfile` JSON. Until those
exist, `from_spec` reads the resume spec with a deliberately literal rule, so
the evidence agent can run end to end:

  "Python (Advanced)" in Skills      -> level stated in the qualifier
  skill named in a project/job entry -> Intermediate (used on real work)
  skill only in the Skills list      -> Entry ("appears only in a skills list")
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from generator.github.skill_map import alias_index

from .evidence_models import ApplicantProfile, SkillClaim

QUALIFIERS = {
    "advanced": 3, "expert": 3, "proficient": 3,
    "intermediate": 2, "working knowledge": 2,
    "entry": 1, "beginner": 1, "basic": 1, "familiar": 1,
}
_QUALIFIED = re.compile(r"^(?P<name>.+?)\s*\((?P<qualifier>[^)]+)\)\s*$")


def parse_skill(text: str) -> tuple[str, int | None]:
    """A level qualifier sets the level; any other parenthetical is part of the name."""
    match = _QUALIFIED.match(text.strip())
    level = QUALIFIERS.get(match["qualifier"].strip().lower()) if match else None
    if match is None or level is None:
        return text.strip(), None
    return match["name"], level


def from_spec(path: Path) -> ApplicantProfile:
    spec = json.loads(path.read_text(encoding="utf-8"))
    index = alias_index()
    work = spec.get("projects", []) + spec.get("experience", []) + spec.get("leadership", [])
    work_text = " ".join(" ".join([*e.get("tech", []), *e.get("bullets", [])])
                         for e in work).lower()

    claims: dict[str, SkillClaim] = {}
    unmapped = []
    for items in (spec.get("skills") or {}).values():
        for raw in items:
            name, level = parse_skill(raw)
            skill_id = index.get(name.lower())
            if skill_id is None:
                unmapped.append(raw)
                continue
            if level is None:
                level = 2 if name.lower() in work_text else 1
            claim = SkillClaim(skill_id=skill_id, level=level,
                               evidence_quote=f"Skills: {raw}",
                               reasoning="read literally from the resume spec")
            if skill_id not in claims or claims[skill_id].level < level:
                claims[skill_id] = claim
    return ApplicantProfile(applicant_id=spec["applicant_id"], skills=list(claims.values()),
                            unmapped=unmapped, source=f"resume_spec:{path.name}")


def to_skill_id(name: str) -> str | None:
    """Any spelling the profile agent uses -> a taxonomy.json id, or None."""
    index = alias_index()
    key = name.strip().lower()
    for candidate in (key, re.sub(r"\s*\(.*\)$", "", key), re.sub(r"[\s._-]+", "", key)):
        if candidate in index:
            return index[candidate]
    squashed = {re.sub(r"[\s._/&-]+", "", k): v for k, v in index.items()}
    return squashed.get(re.sub(r"[\s._/&-]+", "", key))


def from_profile_payload(data: dict) -> ApplicantProfile:
    """The profile agent's ApplicantProfile, normalised onto taxonomy.json.

    Its `canonical_skill` is free text; anything that is not a taxonomy skill is
    kept in `unmapped` and never verified. Two spellings of one skill keep the
    higher claim, since that is the claim worth checking.
    """
    claims: dict[str, SkillClaim] = {}
    names: dict[str, dict[str, int]] = {}
    unmapped = list(data.get("unmapped", []))
    for skill in data.get("skills", []):
        name = skill.get("skill_id") or skill.get("canonical_skill") or ""
        skill_id = to_skill_id(name)
        if skill_id is None:
            unmapped.append(name)
            continue
        level = int(skill.get("claimed_level") or skill.get("level") or 1)
        quotes = [e.get("text", "") for e in skill.get("evidence", []) if isinstance(e, dict)]
        claim = SkillClaim(skill_id=skill_id, level=level,
                           evidence_quote=quotes[0] if quotes else skill.get("evidence_quote"),
                           reasoning=skill.get("reasoning"))
        names.setdefault(skill_id, {})[name] = level
        if skill_id not in claims or claims[skill_id].level < level:
            claims[skill_id] = claim
    skills = [c.model_copy(update={"source_names": names[c.skill_id]}) for c in claims.values()]
    return ApplicantProfile(applicant_id=data["applicant_id"], skills=skills,
                            unmapped=unmapped, source="profile_agent")


def from_profile_agent(path: Path) -> ApplicantProfile:
    profile = from_profile_payload(json.loads(path.read_text(encoding="utf-8")))
    return profile.model_copy(update={"source": f"profile_agent:{path.name}"})
