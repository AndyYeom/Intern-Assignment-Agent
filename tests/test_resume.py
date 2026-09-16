"""Tests for resume generation - schema, drafting, exclusivity and rendering."""
from __future__ import annotations

import pytest

from generator.resume import render, roster
from generator.resume.draft import draft, draft_projects, draft_skills
from generator.resume.schema import (
    SECTION_ORDER,
    Education,
    Entry,
    ResumeInfo,
)
from generator.schemas import GitHubProfile, RepoRecord, SkillEvidence


def _profile() -> GitHubProfile:
    return GitHubProfile(
        login="testuser",
        name="Test User",
        html_url="https://github.com/testuser",
        repos=[
            RepoRecord(
                name="ferry-api", full_name="testuser/ferry-api",
                html_url="https://github.com/testuser/ferry-api",
                description="scheduling api for the island ferry",
                created_at="2024-03-01T00:00:00Z", pushed_at="2024-11-01T00:00:00Z",
                languages={"Python": 40000}, primary_language="Python",
                file_count=30, stargazers=6,
                manifests={"requirements.txt": ["fastapi", "pytest"]},
                has_ci=True, has_tests=True,
                commits={"count": 60, "active_days": 22, "span_days": 240},
            )
        ],
        skill_evidence=[
            SkillEvidence(skill_id="python", max_strength=1.0, repos=["testuser/ferry-api"]),
            SkillEvidence(skill_id="flask-fastapi", max_strength=0.9, repos=["testuser/ferry-api"]),
            # Below the floor - must not reach the resume.
            SkillEvidence(skill_id="kubernetes", max_strength=0.2, repos=["testuser/ferry-api"]),
        ],
    )


def _info(**kwargs) -> ResumeInfo:
    base = {"github_login": "testuser", "first_name": "Ada", "last_name": "Okonkwo",
            "education": Education(major="Computer Science", graduation="June 2026")}
    base.update(kwargs)
    return ResumeInfo(**base)


def test_draft_rejects_mismatched_profile():
    """A crossed pair would silently attach one person's repos to another's name."""
    with pytest.raises(ValueError):
        draft(_profile(), _info(github_login="someone_else"))


def test_draft_projects_are_backed_by_real_repos():
    projects = draft_projects(_profile())
    assert projects and projects[0].link == "https://github.com/testuser/ferry-api"
    assert any("60 commits" in b for b in projects[0].bullets)


def test_weak_signals_do_not_become_resume_skills():
    """The honest draft must not claim a skill from a repo-name match alone."""
    skills = draft_skills(_profile())
    flat = {s for items in skills.values() for s in items}
    assert "Python" in flat
    assert "Kubernetes" not in flat


def test_career_stage_reorders_sections():
    student = draft(_profile(), _info(career_stage="student"))
    switcher = draft(_profile(), _info(career_stage="switcher"))
    assert student.sections.index("projects") < student.sections.index("experience")
    assert switcher.sections.index("experience") < switcher.sections.index("education")
    assert set(SECTION_ORDER) == {"student", "intern", "new_grad", "switcher"}


def test_experience_comes_from_info_not_github():
    """Employment cannot be read off GitHub; it must be supplied."""
    assert draft(_profile(), _info()).experience == []
    job = Entry(title="SWE Intern", organization="Acme", start="Jun 2025", end="Aug 2025")
    assert draft(_profile(), _info(experience=[job])).experience == [job]


def test_render_html_contains_the_substance():
    spec = draft(_profile(), _info(email="ada@example.edu"))
    html = render.to_html(spec)
    assert "ADA OKONKWO" not in html  # name is upper-cased by CSS, not in markup
    assert "Ada Okonkwo" in html
    assert "ada@example.edu" in html
    assert "Ferry API" in html
    assert "Massachusetts Institute of Technology" in html


def test_photo_is_optional():
    with_photo = render.to_html(draft(_profile(), _info(photo=True)))
    without = render.to_html(draft(_profile(), _info(photo=False)))
    assert "data:image/png;base64," in with_photo
    assert "data:image/png;base64," not in without


def test_html_escapes_injected_markup():
    spec = draft(_profile(), _info(first_name="<script>alert(1)</script>"))
    assert "<script>" not in render.to_html(spec)


def test_roster_batches_are_exclusive_and_cover_everyone(tmp_path):
    logins = [f"user{i:02d}" for i in range(40)]
    payload = roster.plan(batches=5, logins=logins, out=tmp_path / "roster.json")

    batches = [set(b["logins"]) for b in payload["batches"]]
    assert sum(len(b) for b in batches) == 40
    assert set().union(*batches) == set(logins)
    for i, left in enumerate(batches):
        for right in batches[i + 1:]:
            assert not (left & right), "a profile appears in two batches"
    assert all(len(b) == 8 for b in batches)


def test_roster_split_is_deterministic(tmp_path):
    logins = [f"user{i:02d}" for i in range(40)]
    first = roster.plan(batches=5, logins=logins, out=tmp_path / "a.json")["batches"]
    second = roster.plan(batches=5, logins=logins, out=tmp_path / "b.json")["batches"]
    assert first == second
