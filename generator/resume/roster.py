"""Partition the GitHub corpus into exclusive batches for parallel authoring.

The guarantee the workflow needs: no GitHub profile may appear in more than one
resume. Two mechanisms enforce it.

  1. `plan()` deterministically assigns each login to exactly one batch, and
     writes that assignment down. Round-robin over a sorted list, so the split
     is stable across re-runs and the strata stay spread across batches.
  2. `verify()` re-checks the written specs afterwards, because an authoring
     agent can always ignore its brief.

Belt and braces on purpose: a duplicated profile would silently corrupt the
day-7 detection count, and it is the kind of error that is invisible once the
resumes look plausible.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generator.config import DATA
from generator.github import normalize

RESUME_DIR = DATA / "resumes"
SPEC_DIR = RESUME_DIR / "specs"
ROSTER_PATH = RESUME_DIR / "roster.json"


def plan(batches: int = 5, logins: list[str] | None = None,
         out: Path | None = None) -> dict[str, Any]:
    """Split the corpus into `batches` exclusive groups.

    `out` overrides where the roster is written, so tests never clobber the
    real one.
    """
    if logins is None:
        profiles = normalize.load_all_profiles()
        logins = [p.login for p in profiles]
        strata = {p.login: p.stratum for p in profiles}
    else:
        strata = {login: None for login in logins}

    if not logins:
        raise RuntimeError("no profiles found - run `generator.cli build` first")

    ordered = sorted(logins)
    assignment: dict[int, list[str]] = defaultdict(list)
    # Round-robin rather than contiguous slices, so each batch gets a mix of strata.
    for index, login in enumerate(ordered):
        assignment[index % batches + 1].append(login)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_profiles": len(ordered),
        "batch_count": batches,
        "rule": "each github_login appears in exactly one batch and one resume",
        "batches": [
            {
                "batch": number,
                "count": len(members),
                "logins": members,
                "strata": [strata.get(m) for m in members],
            }
            for number, members in sorted(assignment.items())
        ],
    }
    target = out or ROSTER_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load() -> dict[str, Any]:
    if not ROSTER_PATH.exists():
        raise RuntimeError(f"no roster at {ROSTER_PATH} - run `resume plan` first")
    return json.loads(ROSTER_PATH.read_text(encoding="utf-8"))


def batch_logins(number: int) -> list[str]:
    for batch in load()["batches"]:
        if batch["batch"] == number:
            return batch["logins"]
    raise KeyError(f"no batch {number} in the roster")


def spec_paths(include_drafts: bool = False) -> list[Path]:
    """Authored specs. `_draft_*.json` is scaffolding, not a finished resume."""
    if not SPEC_DIR.exists():
        return []
    paths = sorted(SPEC_DIR.glob("*.json"))
    if include_drafts:
        return paths
    return [p for p in paths if not p.name.startswith("_draft_")]


def verify() -> dict[str, Any]:
    """Check the written specs against the roster. This is the gate before rendering."""
    problems: list[str] = []
    seen: Counter[str] = Counter()
    by_login: dict[str, list[str]] = defaultdict(list)

    for path in spec_paths():
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        login = spec.get("github_login")
        if not login:
            problems.append(f"{path.name}: missing github_login")
            continue
        seen[login] += 1
        by_login[login].append(path.name)

    for login, count in seen.items():
        if count > 1:
            problems.append(
                f"github_login {login!r} used by {count} resumes: {', '.join(by_login[login])}"
            )

    expected: set[str] = set()
    if ROSTER_PATH.exists():
        for batch in load()["batches"]:
            expected.update(batch["logins"])

        missing = sorted(expected - set(seen))
        extra = sorted(set(seen) - expected)
        if missing:
            problems.append(f"{len(missing)} rostered profiles have no resume: "
                            f"{', '.join(missing[:10])}")
        if extra:
            problems.append(f"{len(extra)} resumes reference profiles not on the roster: "
                            f"{', '.join(extra[:10])}")

    return {
        "specs": len(spec_paths()),
        "distinct_logins": len(seen),
        "expected": len(expected),
        "ok": not problems,
        "problems": problems,
    }
