"""Stable pseudonymous applicant IDs: `applicant0001`, `applicant0002`, ...

Profile files are named by ID rather than GitHub login, so the data directory
does not read as a list of real people. The login stays inside each profile,
because the evidence agent must cite repository URLs, which contain it anyway.

IDs live on the candidate records in candidates.json - the append-only record of
everyone ever examined - so there is no separate mapping file. An ID is assigned
once and never changes or gets reused, even if a profile is later deleted.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from generator import config
from generator.github import sampler

ID_PATTERN = re.compile(r"^applicant\d{4}$")

# Earlier versions kept IDs in a separate file; folded in on first use.
_LEGACY_REGISTRY = config.GITHUB_DATA / "applicant_ids.json"


def load() -> dict[str, str]:
    """login -> applicant ID, for everyone who has one."""
    return {c["login"]: c["applicant_id"] for c in sampler.load_state().get("candidates", [])
            if c.get("applicant_id")}


def _format(number: int) -> str:
    return f"applicant{number:04d}"


def assign(logins: list[str]) -> dict[str, str]:
    """Give every login without an ID the next free one, in the order given."""
    state = sampler.load_state()
    candidates: list[dict[str, Any]] = state.setdefault("candidates", [])
    by_login = {c["login"]: c for c in candidates}

    legacy: dict[str, str] = {}
    if _LEGACY_REGISTRY.exists():
        legacy = json.loads(_LEGACY_REGISTRY.read_text(encoding="utf-8"))

    changed = False
    for login, applicant_id in legacy.items():
        entry = by_login.get(login)
        if entry is not None and not entry.get("applicant_id"):
            entry["applicant_id"] = applicant_id
            changed = True

    used = [int(c["applicant_id"].removeprefix("applicant")) for c in candidates
            if ID_PATTERN.match(c.get("applicant_id") or "")]
    used += [int(v.removeprefix("applicant")) for v in legacy.values() if ID_PATTERN.match(v)]
    next_number = max(used, default=0) + 1

    for login in logins:
        entry = by_login.get(login)
        if entry is None:
            # Collected by explicit login rather than found by `sample`.
            entry = {"login": login, "html_url": f"https://github.com/{login}",
                     "stratum": "manual", "query": "", "selected": True,
                     "discovered_at": datetime.now(UTC).isoformat()}
            candidates.append(entry)
            by_login[login] = entry
            changed = True
        if not entry.get("applicant_id"):
            entry["applicant_id"] = _format(next_number)
            next_number += 1
            changed = True

    if changed:
        sampler.write_state(state)
    if _LEGACY_REGISTRY.exists():
        _LEGACY_REGISTRY.unlink()
    return {c["login"]: c["applicant_id"] for c in candidates if c.get("applicant_id")}


def id_for(login: str) -> str | None:
    return load().get(login)
