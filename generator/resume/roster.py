"""Partition the placed corpus into exclusive batches for parallel authoring.

The guarantee the workflow needs: no profile appears in more than one resume.
Everything is keyed on `applicant_id`, the one identifier every file shares.

  1. `plan()` deterministically assigns each applicant to exactly one batch.
     Round-robin over a sorted list, so the split is stable across re-runs.
  2. `verify()` re-checks the written specs, because an author can always
     ignore their brief. `render` runs it first and refuses on any problem.

Belt and braces on purpose: a duplicated or mismatched profile would silently
corrupt the day-7 detection count, and is invisible once the resumes look right.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from generator.config import DATA

RESUME_DIR = DATA / "resumes"
SPEC_DIR = RESUME_DIR / "specs"
ROSTER_PATH = RESUME_DIR / "roster.json"
DRAFT_PREFIX = "_draft_"


def spec_path(applicant_id: str, *, draft: bool = False) -> Path:
    """Specs are named by applicant ID, so two invented "Ada Okonkwo"s cannot collide."""
    return SPEC_DIR / f"{DRAFT_PREFIX if draft else ''}{applicant_id}.json"


def plan(batches: int = 5, applicant_ids: list[str] | None = None,
         out: Path | None = None) -> dict[str, Any]:
    """Split the placed corpus into `batches` exclusive groups."""
    if applicant_ids is None:
        from generator.github import assign

        applicant_ids = [p.applicant_id for p in assign.current().placements]
    if not applicant_ids:
        raise RuntimeError("no placed profiles - run `generator gh build` first")

    groups: dict[int, list[str]] = defaultdict(list)
    for index, applicant_id in enumerate(sorted(applicant_ids)):
        groups[index % batches + 1].append(applicant_id)

    payload = {
        "batches": [{"batch": number, "applicant_ids": members}
                    for number, members in sorted(groups.items())],
    }
    target = out or ROSTER_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load() -> dict[str, Any]:
    if not ROSTER_PATH.exists():
        raise RuntimeError(f"no roster at {ROSTER_PATH} - run `generator re plan` first")
    return json.loads(ROSTER_PATH.read_text(encoding="utf-8"))


def batch_ids(number: int) -> list[str]:
    for batch in load()["batches"]:
        if batch["batch"] == number:
            return batch["applicant_ids"]
    raise KeyError(f"no batch {number} in the roster")


def rostered_ids() -> set[str]:
    if not ROSTER_PATH.exists():
        return set()
    return {i for batch in load()["batches"] for i in batch["applicant_ids"]}


def spec_paths(include_drafts: bool = False) -> list[Path]:
    """Authored specs. `_draft_*.json` is scaffolding, not a finished resume."""
    if not SPEC_DIR.exists():
        return []
    paths = sorted(SPEC_DIR.glob("*.json"))
    return paths if include_drafts else [p for p in paths if not p.name.startswith(DRAFT_PREFIX)]


def verify() -> dict[str, Any]:
    """Check authored specs against the roster and the corpus. The gate before rendering."""
    from generator.github import assign, ids

    problems: list[str] = []
    seen: Counter[str] = Counter()
    files: dict[str, list[str]] = defaultdict(list)
    login_by_id = {v: k for k, v in ids.load().items()}

    for path in spec_paths():
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        applicant_id = spec.get("applicant_id")
        if not applicant_id:
            problems.append(f"{path.name}: missing applicant_id")
            continue
        if path.stem != applicant_id:
            problems.append(f"{path.name}: file name must be {applicant_id}.json")
        if login_by_id.get(applicant_id) != spec.get("github_login"):
            problems.append(f"{path.name}: github_login does not match {applicant_id}")
        seen[applicant_id] += 1
        files[applicant_id].append(path.name)

    for applicant_id, count in seen.items():
        if count > 1:
            problems.append(f"{applicant_id} has {count} resumes: {', '.join(files[applicant_id])}")

    expected = rostered_ids()
    if expected:
        missing = sorted(expected - set(seen))
        extra = sorted(set(seen) - expected)
        if missing:
            problems.append(f"{len(missing)} rostered applicants have no resume: "
                            f"{', '.join(missing[:10])}")
        if extra:
            problems.append(f"{len(extra)} resumes are for applicants not on the roster: "
                            f"{', '.join(extra[:10])}")

    if seen:
        placed = {p.applicant_id for p in assign.current().placements}
        unplaced = sorted(set(seen) - placed)
        if unplaced:
            problems.append(f"{len(unplaced)} resumes are for applicants no longer placed: "
                            f"{', '.join(unplaced[:10])}")

    return {"specs": sum(seen.values()), "applicants": len(seen), "expected": len(expected),
            "ok": not problems, "problems": problems}
