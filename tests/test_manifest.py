"""Tests for the applicant manifest (data/applicants.csv)."""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor

import pytest

from generator.resume import manifest
from generator.resume.schema import ResumeSpec


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Never touch the real manifest."""
    monkeypatch.setattr(manifest, "MANIFEST_PATH", tmp_path / "applicants.csv")
    monkeypatch.setattr(manifest, "LOCK_PATH", tmp_path / ".lock")


def _spec(login: str, first: str, last: str) -> ResumeSpec:
    return ResumeSpec(github_login=login, first_name=first, last_name=last, batch=1)


def test_missing_manifest_reads_as_empty():
    assert manifest.load() == []
    assert manifest.used_logins() == set()


def test_upsert_assigns_sequential_idx():
    manifest.upsert([manifest.row_for(_spec("alpha", "Ada", "A"))])
    manifest.upsert([manifest.row_for(_spec("bravo", "Ben", "B"))])
    rows = manifest.load()
    assert [r["idx"] for r in rows] == ["0", "1"]
    assert [r["github_login"] for r in rows] == ["alpha", "bravo"]


def test_reupsert_keeps_idx_stable():
    """A re-render must not renumber everyone."""
    manifest.upsert([manifest.row_for(_spec("alpha", "Ada", "A"))])
    manifest.upsert([manifest.row_for(_spec("bravo", "Ben", "B"))])
    manifest.upsert([manifest.row_for(_spec("alpha", "Ada", "Renamed"))])

    rows = {r["github_login"]: r for r in manifest.load()}
    assert rows["alpha"]["idx"] == "0"
    assert rows["bravo"]["idx"] == "1"
    assert rows["alpha"]["last_name"] == "Renamed"
    assert len(manifest.load()) == 2, "upsert must update, not duplicate"


def test_used_logins_answers_is_this_profile_taken():
    manifest.upsert([manifest.row_for(_spec("alpha", "Ada", "A"))])
    assert manifest.used_logins() == {"alpha"}
    assert "bravo" not in manifest.used_logins()


def test_concurrent_upserts_do_not_lose_rows():
    """Several authoring agents render at once; naive appends interleave."""
    specs = [_spec(f"user{i:02d}", f"First{i}", f"Last{i}") for i in range(12)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda s: manifest.upsert([manifest.row_for(s)]), specs))

    rows = manifest.load()
    assert len(rows) == 12
    assert len({r["github_login"] for r in rows}) == 12
    assert sorted(int(r["idx"]) for r in rows) == list(range(12))


def test_written_file_is_valid_csv_with_expected_header():
    manifest.upsert([manifest.row_for(_spec("alpha", "Ada", "A"))])
    with manifest.MANIFEST_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        assert next(reader) == manifest.COLUMNS


def test_commas_in_names_survive_the_round_trip():
    manifest.upsert([manifest.row_for(_spec("alpha", "Ada, Jr.", 'O"Brien'))])
    row = manifest.load()[0]
    assert row["first_name"] == "Ada, Jr."
    assert row["last_name"] == 'O"Brien'


def test_paths_are_repo_relative():
    """Absolute paths would break the moment the repo is cloned elsewhere."""
    manifest.upsert([manifest.row_for(_spec("alpha", "Ada", "A"))])
    row = manifest.load()[0]
    assert row["github_profile"] == "data/githubs/profiles/alpha.json"
    assert not row["github_profile"].startswith("/")


def test_manifest_carries_no_exaggeration_column():
    """The answer key must not live in the index the evidence agent reads."""
    assert not any("exagger" in c or "planted" in c or "truth" in c
                   for c in manifest.COLUMNS)
