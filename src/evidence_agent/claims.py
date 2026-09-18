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

from .schemas import ApplicantProfile, SkillClaim

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


def from_profile_agent(path: Path) -> ApplicantProfile:
    """Accepts the profile agent's JSON; `canonical_skill` is read as `skill_id`."""
    data = json.loads(path.read_text(encoding="utf-8"))
    skills = [{**s, "skill_id": s.get("skill_id") or s.get("canonical_skill")}
              for s in data.get("skills", [])]
    return ApplicantProfile.model_validate({**data, "skills": skills,
                                            "source": f"profile_agent:{path.name}"})
