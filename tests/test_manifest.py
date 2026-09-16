"""Tests for the applicant manifest (data/applicants.csv)."""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor

import pytest

from generator.resume import manifest
from generator.resume.schema import ResumeSpec


def _spec(n: int, first: str = "Ada", last: str = "Okonkwo") -> ResumeSpec:
    return ResumeSpec(github_login=f"login{n}", applicant_id=f"applicant{n:04d}",
                      first_name=first, last_name=last, batch=1)


def test_missing_manifest_reads_as_empty():
    assert manifest.load() == []
    assert manifest.used_ids() == set()


def test_rows_are_keyed_and_sorted_by_applicant_id():
    manifest.upsert([manifest.row_for(_spec(7))])
    manifest.upsert([manifest.row_for(_spec(2))])
    assert [r["applicant_id"] for r in manifest.load()] == ["applicant0002", "applicant0007"]


def test_reupsert_updates_instead_of_duplicating():
    manifest.upsert([manifest.row_for(_spec(1))])
    manifest.upsert([manifest.row_for(_spec(1, last="Renamed"))])
    rows = manifest.load()
    assert len(rows) == 1
    assert rows[0]["last_name"] == "Renamed"


def test_two_applicants_with_the_same_invented_name_stay_distinct():
    manifest.upsert([manifest.row_for(_spec(1)), manifest.row_for(_spec(2))])
    rows = manifest.load()
    assert len(rows) == 2
    assert rows[0]["github_profile"] != rows[1]["github_profile"]


def test_used_ids_answers_is_this_applicant_taken():
    manifest.upsert([manifest.row_for(_spec(1))])
    assert manifest.used_ids() == {"applicant0001"}


def test_concurrent_upserts_do_not_lose_rows():
    """Several authors render at once; naive appends interleave."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda n: manifest.upsert([manifest.row_for(_spec(n))]), range(12)))
    assert sorted(r["applicant_id"] for r in manifest.load()) == \
        [f"applicant{n:04d}" for n in range(12)]


def test_rewriting_unchanged_rows_is_byte_identical():
    """No timestamps: re-rendering an unchanged resume produces no git diff."""
    manifest.upsert([manifest.row_for(_spec(1))])
    first = manifest.MANIFEST_PATH.read_bytes()
    manifest.upsert([manifest.row_for(_spec(1))])
    assert manifest.MANIFEST_PATH.read_bytes() == first


def test_header_and_quoting():
    manifest.upsert([manifest.row_for(_spec(1, first="Ada, Jr.", last='O"Brien'))])
    with manifest.MANIFEST_PATH.open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == manifest.COLUMNS
    row = manifest.load()[0]
    assert (row["first_name"], row["last_name"]) == ("Ada, Jr.", 'O"Brien')


def test_profile_path_is_repo_relative_and_named_by_id():
    manifest.upsert([manifest.row_for(_spec(42))])
    assert manifest.load()[0]["github_profile"] == "data/githubs/profiles/applicant0042.json"


def test_spec_without_applicant_id_is_rejected():
    with pytest.raises(ValueError):
        manifest.row_for(ResumeSpec(github_login="x", first_name="A", last_name="B"))


def test_no_redundant_or_answer_key_columns():
    assert "idx" not in manifest.COLUMNS
    assert "resume_html" not in manifest.COLUMNS
    assert "rendered_at" not in manifest.COLUMNS
    assert not any(k in c for c in manifest.COLUMNS for k in ("exagger", "planted", "truth"))
