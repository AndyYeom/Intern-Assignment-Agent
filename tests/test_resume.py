"""Tests for resume generation - schema, drafting, exclusivity and rendering."""
from __future__ import annotations

import pytest

from generator.resume import render
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
        applicant_id="applicant0001",
        login="testuser",
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
                skill_relevant=True,
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
    spec = draft(_profile(), _info(email="ada@northbridge.example"))
    html = render.to_html(spec)
    assert "ADA OKONKWO" not in html  # name is upper-cased by CSS, not in markup
    assert "Ada Okonkwo" in html
    assert "ada@northbridge.example" in html
    assert "Ferry API" in html
    assert "Northbridge Institute of Technology" in html


def test_photo_is_optional():
    with_photo = render.to_html(draft(_profile(), _info(photo=True)))
    without = render.to_html(draft(_profile(), _info()))
    assert "data:image/jpeg;base64," in with_photo
    assert "data:image/jpeg;base64," not in without


def test_photo_is_downscaled_before_embedding():
    """The raw 350px PNG was a third of every PDF."""
    import base64
    import io

    from PIL import Image

    uri = render._photo_data_uri()
    assert uri is not None
    data = base64.b64decode(uri.split(",", 1)[1])
    with Image.open(io.BytesIO(data)) as image:
        assert max(image.size) <= render.PHOTO_PX
    assert len(data) < 4_000


def test_real_repo_links_are_never_rendered():
    """A project link carries the real username; the resume identity is invented."""
    spec = draft(_profile(), _info())
    assert spec.projects[0].link == "https://github.com/testuser/ferry-api"
    html = render.to_html(spec)
    assert "github.com/testuser" not in html
    assert "testuser" not in html.replace("github.example.com/ada-okonkwo", "")


def test_pdf_stays_small():
    """Committed to the repo, so size matters. A full one-page resume is ~20 KB."""
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    pdf = render.render_pdf(draft(_profile(), _info(email="ada@northbridge.example", photo=True)),
                            render.TEMPLATE_A)
    assert pdf is not None
    assert len(pdf) < 40_000


def test_html_escapes_injected_markup():
    spec = draft(_profile(), _info(first_name="<script>alert(1)</script>"))
    assert "<script>" not in render.to_html(spec)


def test_login_named_repos_never_put_the_login_on_a_resume():
    profile = _profile()
    profile.repos.append(profile.repos[0].model_copy(update={
        "name": "testuser.github.io", "full_name": "testuser/testuser.github.io",
        "stargazers": 50}))
    titles = [e.title for e in draft_projects(profile, handle="ada-okonkwo")]
    assert "Personal Website" in titles
    assert not any("testuser" in t.lower() for t in titles)


def test_irrelevant_repos_are_not_resume_projects():
    profile = _profile()
    profile.repos.append(profile.repos[0].model_copy(update={
        "name": "notes", "full_name": "testuser/notes", "skill_relevant": False,
        "stargazers": 999}))
    assert [e.title for e in draft_projects(profile)] == ["Ferry API"]


def test_layout_follows_mit_template_a():
    """Section names, order and shape come from data/static/MITResumeTemplateA.docx."""
    info = _info(career_stage="intern", email="ada@northbridge.example", phone="(617) 555-0142",
                 location="Port Calder",
                 experience=[Entry(title="SWE Intern", organization="Acme", location="Tidewell",
                                   start="Jun 2025", end="Aug 2025", bullets=["Built a thing"])],
                 leadership=[Entry(title="Lead", organization="Hacking Club", start="2024")])
    spec = draft(_profile(), info)
    spec.education.honors = ["Dean's List"]
    html = render.to_html(spec)

    titles = ["Education", "Experience", "Projects", "Activities &amp; Extracurriculars",
              "Awards &amp; Accomplishments", "Skills &amp; Interests"]
    positions = [html.index(f"<h2>{t}</h2>") for t in titles]
    assert positions == sorted(positions)
    import re

    visible = re.sub(r"<[^>]+>", "", html)
    assert "Port Calder | (617) 555-0142 | ada@northbridge.example" in visible
    assert '<span class="nowrap">github.example.com/ada-okonkwo</span>' in html
    assert "<b>Acme</b>, Tidewell" in html
    assert (render.TEMPLATE_A.margin_in, render.TEMPLATE_A.body_pt) == (1.0, 11.0)
    assert "margin: 1.0in" in render.CSS and "font-size: 11.0pt" in render.CSS


def test_template_a_has_no_photo_by_default():
    assert "data:image/jpeg" not in render.to_html(draft(_profile(), _info()))


def test_overflow_past_one_page_is_detected():
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    spec = draft(_profile(), _info())
    assert render.page_count(spec) == 1
    long = spec.model_copy(update={"projects": spec.projects * 12})
    assert render.page_count(long) > 1


def test_award_shows_a_single_date_not_a_range():
    spec = draft(_profile(), _info())
    spec.awards = [Entry(title="Essay Distinction", start="Mar 2026")]
    html = render.to_html(spec)
    assert "Mar 2026" in html
    assert "Mar 2026 &ndash; Present" not in html


def test_single_commit_is_not_pluralised():
    profile = _profile()
    profile.repos[0].commits = {"count": 1, "active_days": 1}
    bullets = draft_projects(profile)[0].bullets
    assert "1 commit over 1 active day." in bullets


def test_every_layout_stays_within_mit_guidance():
    """MIT CAPD: 10-12pt body text, 0.5-1in margins. Tightening never goes past that."""
    assert render.LAYOUTS[0] is render.TEMPLATE_A
    for layout in render.LAYOUTS:
        assert 10.0 <= layout.body_pt <= 12.0
        assert 0.5 <= layout.margin_in <= 1.0
    sizes = [(l.body_pt, l.margin_in, l.gap_pt) for l in render.LAYOUTS]
    assert sizes == sorted(sizes, reverse=True), "layouts must only ever tighten"


def test_an_overflowing_resume_gets_a_tighter_layout_with_nothing_cut():
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    spec = draft(_profile(), _info())
    base = spec.projects[0]
    long = spec.model_copy(update={"projects": [base.model_copy(update={"bullets": base.bullets * 2})
                                                for _ in range(4)]})
    assert render.page_count(long) > 1
    layout = render.fitted_layout(long)
    assert layout is not None and layout.name != render.TEMPLATE_A.name
    assert render.page_count(long, layout) == 1


def test_render_pdf_refuses_to_write_more_than_one_page():
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    spec = draft(_profile(), _info())
    huge = spec.model_copy(update={"projects": spec.projects * 15})
    with pytest.raises(ValueError, match="refusing to write a multi-page resume"):
        render.render_pdf(huge, render.TEMPLATE_A)
