"""The applicant manifest: one row per person, pairing GitHub profile to resume.

`data/applicants.csv` is the index an agent reads to answer "who exists, where
is their profile, where is their resume". Without it, consuming the corpus means
globbing two directories and joining them on a login parsed out of a filename.

Two properties matter more than they look:

  * **Derived, not authoritative.** Every row is reconstructable from the spec
    files on disk, so the manifest can never disagree with reality for long -
    `rebuild()` regenerates it. The filesystem stays the source of truth.

  * **Safe under parallel writes.** Several authoring agents render at once, and
    a naive append interleaves partial lines. Every write takes an exclusive
    lock, re-reads, upserts and replaces the file atomically.

Deliberately absent: any column marking a planted exaggeration. That answer key
belongs to whoever plants them, not in the shared index the evidence agent reads.
"""
from __future__ import annotations

import csv
import fcntl
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generator.config import DATA, ROOT
from generator.resume.schema import ResumeSpec

MANIFEST_PATH = DATA / "applicants.csv"
LOCK_PATH = DATA / ".applicants.lock"

COLUMNS = [
    "idx",
    "first_name",
    "last_name",
    "github_login",
    "github_profile",
    "resume_pdf",
    "resume_html",
    "spec",
    "career_stage",
    "batch",
    "rendered_at",
]


def _rel(path: Path | str | None) -> str:
    """Store repo-relative paths so the manifest survives being moved."""
    if not path:
        return ""
    path = Path(path)
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


@contextmanager
def _locked():
    """Exclusive advisory lock, so parallel renders cannot interleave."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def load() -> list[dict[str, str]]:
    """Read the manifest. Returns [] if it does not exist yet."""
    if not MANIFEST_PATH.exists():
        return []
    with MANIFEST_PATH.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write(rows: list[dict[str, Any]]) -> None:
    """Atomic replace - a reader never sees a half-written manifest."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})
    tmp.replace(MANIFEST_PATH)


def row_for(spec: ResumeSpec, *, pdf: Path | None = None, html: Path | None = None,
            spec_path: Path | None = None) -> dict[str, Any]:
    from generator.config import PROFILES_DIR

    return {
        "first_name": spec.first_name,
        "last_name": spec.last_name,
        "github_login": spec.github_login,
        "github_profile": _rel(PROFILES_DIR / f"{spec.github_login}.json"),
        "resume_pdf": _rel(pdf),
        "resume_html": _rel(html),
        "spec": _rel(spec_path),
        "career_stage": spec.career_stage,
        "batch": spec.batch if spec.batch is not None else "",
        "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def upsert(new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert or update rows, keyed on github_login. Existing idx values are kept
    so a person's index stays stable across re-renders."""
    with _locked():
        existing = load()
        by_login = {row["github_login"]: row for row in existing}

        next_idx = max((int(r["idx"]) for r in existing if r.get("idx", "").isdigit()),
                       default=-1) + 1

        for row in new_rows:
            login = row["github_login"]
            if login in by_login:
                row["idx"] = by_login[login]["idx"]
            else:
                row["idx"] = next_idx
                next_idx += 1
            by_login[login] = row

        merged = sorted(by_login.values(), key=lambda r: int(r["idx"]))
        _write(merged)
        return merged


def used_logins() -> set[str]:
    """GitHub profiles that already have a resume. The 'is this taken' check."""
    return {row["github_login"] for row in load() if row.get("github_login")}


def rebuild(specs: list[tuple[ResumeSpec, Path]], rendered_dir: Path) -> list[dict[str, Any]]:
    """Regenerate the manifest from what is actually on disk."""
    rows = []
    for spec, spec_path in specs:
        pdf = rendered_dir / f"{spec.slug}.pdf"
        html = rendered_dir / f"{spec.slug}.html"
        rows.append(row_for(
            spec,
            pdf=pdf if pdf.exists() else None,
            html=html if html.exists() else None,
            spec_path=spec_path,
        ))
    with _locked():
        for index, row in enumerate(sorted(rows, key=lambda r: r["github_login"])):
            row["idx"] = index
        _write(sorted(rows, key=lambda r: int(r["idx"])))
    return rows
