"""The applicant manifest: one row per applicant, pairing GitHub profile to resume.

`data/applicants.csv` is the index an agent reads to answer "who exists, where
is their profile, where is their resume". Keyed on `applicant_id`.

  * **Derived, not authoritative.** Every row is reconstructable from the specs
    on disk; `rebuild()` regenerates it.
  * **Safe under parallel writes.** Several authors render at once. Every write
    takes an exclusive lock, re-reads, upserts and replaces the file atomically.
  * **Stable.** No timestamps, and rows sorted by applicant ID, so re-rendering
    unchanged resumes produces no git diff.

Deliberately absent: any column marking a planted exaggeration. That answer key
belongs with whoever plants them, not in the index the evidence agent reads.
"""
from __future__ import annotations

import csv
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from generator.config import DATA
from generator.resume.schema import ResumeSpec

MANIFEST_PATH = DATA / "applicants.csv"
LOCK_PATH = DATA / ".applicants.lock"

COLUMNS = [
    "applicant_id",
    "first_name",
    "last_name",
    "github_login",
    "github_profile",
    "resume_pdf",
    "spec",
    "career_stage",
    "batch",
]

# A lock file created with O_EXCL: atomic on macOS, Linux and Windows alike.
LOCK_TIMEOUT_SECONDS = 60
LOCK_STALE_SECONDS = 120   # a crashed render must not block everyone forever


def _rel(path: Path | str | None) -> str:
    """Repo-relative paths, so the manifest survives being cloned elsewhere."""
    if not path:
        return ""
    path = Path(path)
    try:
        return path.resolve().relative_to(DATA.resolve().parent).as_posix()
    except ValueError:
        return path.as_posix()


@contextmanager
def _locked():
    """Exclusive lock, so parallel renders cannot interleave."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            handle = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - LOCK_PATH.stat().st_mtime > LOCK_STALE_SECONDS:
                    LOCK_PATH.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not lock {MANIFEST_PATH.name}; "
                                   f"delete {LOCK_PATH} if no render is running") from None
            time.sleep(0.05)
    os.close(handle)
    try:
        yield
    finally:
        LOCK_PATH.unlink(missing_ok=True)


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
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["applicant_id"]):
            writer.writerow({column: row.get(column, "") for column in COLUMNS})
    tmp.replace(MANIFEST_PATH)


def row_for(spec: ResumeSpec, *, pdf: Path | None = None,
            spec_file: Path | None = None) -> dict[str, Any]:
    from generator.github.normalize import profile_path

    if not spec.applicant_id:
        raise ValueError(f"spec for {spec.github_login} has no applicant_id")
    return {
        "applicant_id": spec.applicant_id,
        "first_name": spec.first_name,
        "last_name": spec.last_name,
        "github_login": spec.github_login,
        "github_profile": _rel(profile_path(spec.applicant_id)),
        "resume_pdf": _rel(pdf),
        "spec": _rel(spec_file),
        "career_stage": spec.career_stage,
        "batch": spec.batch if spec.batch is not None else "",
    }


def upsert(new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert or update rows, keyed on applicant_id."""
    with _locked():
        by_id: dict[str, dict[str, Any]] = {row["applicant_id"]: row for row in load()}
        for row in new_rows:
            by_id[row["applicant_id"]] = row
        rows = list(by_id.values())
        _write(rows)
        return sorted(rows, key=lambda r: r["applicant_id"])


def remove(applicant_ids: list[str]) -> int:
    """Drop rows by applicant_id. Returns how many were removed."""
    targets = set(applicant_ids)
    with _locked():
        rows = load()
        kept = [row for row in rows if row["applicant_id"] not in targets]
        _write(kept)
    return len(rows) - len(kept)


def used_ids() -> set[str]:
    """Applicants that already have a resume."""
    return {row["applicant_id"] for row in load() if row.get("applicant_id")}


def rebuild(specs: list[tuple[ResumeSpec, Path]], rendered_dir: Path) -> list[dict[str, Any]]:
    """Regenerate the manifest from what is actually on disk."""
    rows = []
    for spec, spec_file in specs:
        pdf = rendered_dir / f"{spec.applicant_id}.pdf"
        rows.append(row_for(spec, pdf=pdf if pdf.exists() else None, spec_file=spec_file))
    with _locked():
        _write(rows)
    return sorted(rows, key=lambda r: r["applicant_id"])
