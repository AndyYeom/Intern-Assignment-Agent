"""Tests for `re gen`, `re infoprompt` and `re remove`: every PDF is a recorded pair."""
from __future__ import annotations

import json

import pytest

from generator.github import assign, ids, normalize, sampler
from generator.resume import generate, manifest, prompt, render
from generator.resume.schema import GenRequest
from generator.schemas import GitHubProfile, RepoRecord

IDENTITY = {"first_name": "Ada", "last_name": "Okonkwo", "email": "ada@northbridge.example"}


@pytest.fixture
def applicant():
    """One placed applicant with a built profile, inside the isolated data dir."""
    sampler.write_state({"consumed": {}, "candidates": [
        {"login": "realperson42", "selected": True, "stratum": "go-systems"}]})
    applicant_id = ids.assign(["realperson42"])["realperson42"]
    repos = [RepoRecord(name=f"svc{i}", full_name=f"realperson42/svc{i}",
                        html_url=f"https://github.com/realperson42/svc{i}",
                        description="A Go service by realperson42",
                        languages={"Go": 30_000}, primary_language="Go", file_count=12,
                        skill_relevant=True, commits={"count": 20, "active_days": 9},
                        skill_signals=[{"skill_id": "go", "source": "language",
                                        "strength": 1.0}])
             for i in range(3)]
    normalize.save_profile(GitHubProfile(applicant_id=applicant_id, login="realperson42",
                                         html_url="https://github.com/realperson42",
                                         tier="strict", repos=repos))
    assert applicant_id in assign.current().placed_ids
    return applicant_id


# -- argument parsing --------------------------------------------------------------

def test_appids_and_infos_pair_by_position():
    requests = generate.parse_requests(
        ["applicant0001", "applicant0002"],
        [json.dumps(IDENTITY), json.dumps({**IDENTITY, "first_name": "Luis"})])
    assert [(r.applicant_id, r.first_name) for r in requests] == \
        [("applicant0001", "Ada"), ("applicant0002", "Luis")]


def test_mismatched_counts_are_rejected():
    with pytest.raises(generate.GenError, match="counts must match"):
        generate.parse_requests(["applicant0001", "applicant0002"], [json.dumps(IDENTITY)])


def test_repeated_appids_are_rejected():
    with pytest.raises(generate.GenError, match="repeated"):
        generate.parse_requests(["applicant0001"] * 2, [json.dumps(IDENTITY)] * 2)


def test_info_naming_a_different_applicant_is_rejected():
    info = json.dumps({**IDENTITY, "applicant_id": "applicant0009"})
    with pytest.raises(generate.GenError, match="different applicant"):
        generate.parse_requests(["applicant0001"], [info])


def test_info_can_come_from_a_file(tmp_path):
    path = tmp_path / "ada.json"
    path.write_text(json.dumps(IDENTITY))
    assert generate.parse_requests(["applicant0001"], [f"@{path}"])[0].first_name == "Ada"


def test_apostrophes_escaped_as_the_prompt_instructs_parse_correctly():
    info = '{"first_name": "Dean", "last_name": "O\\u0027Brien"}'
    assert generate.parse_requests(["applicant0001"], [info])[0].last_name == "O\'Brien"


# -- generation -------------------------------------------------------------------

def test_every_generated_pdf_is_recorded_with_its_github_profile(applicant):
    generate.generate(GenRequest(applicant_id=applicant, **IDENTITY))
    rows = manifest.load()
    assert len(rows) == 1
    assert rows[0]["applicant_id"] == applicant
    assert rows[0]["github_login"] == "realperson42"
    assert rows[0]["github_profile"].endswith(f"profiles/{applicant}.json")
    if render.pdf_available():
        assert rows[0]["resume_pdf"].endswith(f"rendered/{applicant}.pdf")
        assert (generate.RENDER_DIR / f"{applicant}.pdf").exists()


def test_pdf_metadata_names_the_applicant_but_never_the_login(applicant):
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    generate.generate(GenRequest(applicant_id=applicant, **IDENTITY))
    html = render.to_html(generate.build_spec(GenRequest(applicant_id=applicant, **IDENTITY))[0])
    assert f"content='{applicant}'" in html
    assert "realperson42" not in html


def test_failed_manifest_write_leaves_no_unrecorded_pdf(applicant, monkeypatch):
    def broken(rows):
        raise TimeoutError("lock")
    monkeypatch.setattr(manifest, "upsert", broken)
    with pytest.raises(TimeoutError):
        generate.generate(GenRequest(applicant_id=applicant, **IDENTITY))
    assert not list(generate.RENDER_DIR.glob("*.pdf"))
    assert not list(generate.RENDER_DIR.glob("*.tmp"))


def test_generating_again_replaces_the_pair(applicant):
    generate.generate(GenRequest(applicant_id=applicant, **IDENTITY))
    generate.generate(GenRequest(applicant_id=applicant, **{**IDENTITY, "first_name": "Bea"}))
    rows = manifest.load()
    assert len(rows) == 1
    assert rows[0]["first_name"] == "Bea"


def test_unplaced_or_unknown_applicants_are_refused(applicant):
    with pytest.raises(generate.GenError, match="no built profile"):
        generate.build_spec(GenRequest(applicant_id="applicant9999", **IDENTITY))


def test_github_login_from_another_applicant_is_refused(applicant):
    request = GenRequest(applicant_id=applicant, github_login="someone-else", **IDENTITY)
    with pytest.raises(generate.GenError, match="different applicant"):
        generate.build_spec(request)


def test_authored_projects_replace_the_draft(applicant):
    request = GenRequest(applicant_id=applicant, **IDENTITY, projects=[
        {"title": "Queue Service", "tech": ["Go"], "bullets": ["Built a queue"]}])
    spec, drafted = generate.build_spec(request)
    assert not drafted
    assert [p.title for p in spec.projects] == ["Queue Service"]


def _just_over_template_a(spec):
    """Grow the resume one project at a time until it first overflows Template A."""
    base = spec.projects[0]
    for count in range(1, 30):
        grown = spec.model_copy(update={"projects": [base] * count})
        if render.page_count(grown, render.TEMPLATE_A) > 1:
            return grown
    raise AssertionError("could not overflow Template A")


def test_layout_tightens_before_any_drafted_content_is_cut(applicant):
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    spec, _ = generate.build_spec(GenRequest(applicant_id=applicant, **IDENTITY))
    longer = _just_over_template_a(spec)
    fitted, layout = generate.fit_one_page(longer, drafted=True)
    assert fitted.projects == longer.projects          # nothing cut
    assert layout.name != render.TEMPLATE_A.name        # the layout tightened instead
    assert render.page_count(fitted, layout) == 1


def test_drafted_projects_are_cut_only_past_the_tightest_layout(applicant):
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    spec, _ = generate.build_spec(GenRequest(applicant_id=applicant, **IDENTITY))
    huge = spec.model_copy(update={"projects": spec.projects * 6})
    fitted, layout = generate.fit_one_page(huge, drafted=True)
    assert len(fitted.projects) < len(huge.projects)
    assert render.page_count(fitted, layout) == 1


def test_authored_overflow_is_refused_and_nothing_is_written(applicant):
    """An author's words are never cut, and a two-page resume is never written."""
    if not render.pdf_available():
        pytest.skip("WeasyPrint system libraries not installed")
    many = [{"title": f"Project {i}", "tech": ["Go"],
             "bullets": [("Built a service handling configuration, retries and structured "
                          "logging for a small command-line tool")] * 3} for i in range(12)]
    with pytest.raises(generate.GenError, match="does not fit one page"):
        generate.generate(GenRequest(applicant_id=applicant, **IDENTITY, projects=many))
    assert manifest.load() == []
    assert not generate.spec_path(applicant).exists()
    assert not list(generate.RENDER_DIR.glob("*.pdf"))


def test_budget_report_names_the_overage(applicant):
    spec, _ = generate.build_spec(GenRequest(applicant_id=applicant, **IDENTITY))
    report = generate.budget_report(spec)
    assert "budget 9" in report and "budget 160" in report and "budget 22" in report


# -- remove -------------------------------------------------------------------------

def test_remove_deletes_the_pair_but_keeps_the_profile(applicant):
    generate.generate(GenRequest(applicant_id=applicant, **IDENTITY))
    generate.remove([applicant])
    assert manifest.load() == []
    assert not generate.spec_path(applicant).exists()
    assert not (generate.RENDER_DIR / f"{applicant}.pdf").exists()
    assert not (generate.RAW_DIR / f"{applicant}.html").exists()
    assert normalize.load_profile(applicant) is not None


def test_remove_can_keep_the_spec(applicant):
    generate.generate(GenRequest(applicant_id=applicant, **IDENTITY))
    generate.remove([applicant], keep_spec=True)
    assert manifest.load() == []
    assert generate.spec_path(applicant).exists()


# -- infoprompt -------------------------------------------------------------------------

def test_infoprompt_is_static_around_the_evidence(applicant):
    block = generate.evidence_block(applicant)
    built = prompt.build(generate.FORMAT, [block], "GUIDE")
    head = prompt.PROMPT.split("{format}")[0]
    assert built.startswith(head)
    assert block.strip() in built
    assert "re gen --appids" in built


def test_infoprompt_never_leaks_the_login_or_links(applicant):
    built = prompt.build(generate.FORMAT, [generate.evidence_block(applicant)])
    assert "realperson42" not in built
    assert "github.com/realperson42" not in built


def test_html_preview_goes_to_raw_not_rendered(applicant):
    generate.generate(GenRequest(applicant_id=applicant, **IDENTITY))
    assert (generate.RAW_DIR / f"{applicant}.html").exists()
    assert not list(generate.RENDER_DIR.glob("*.html"))


# -- fictional identities -------------------------------------------------------------

@pytest.mark.parametrize("field", ["email", "linkedin", "portfolio"])
@pytest.mark.parametrize("value", [
    "ada@mit.edu", "ada@example.edu", "ada@gmail.com",
    "linkedin.com/in/ada-okonkwo", "https://www.linkedin.com/in/ada", "ada.dev",
])
def test_real_domains_are_rejected(field, value):
    """An invented address on a real domain can reach a real person."""
    with pytest.raises(ValueError, match="real domain"):
        GenRequest(applicant_id="applicant0001", **{**IDENTITY, field: value})


@pytest.mark.parametrize("value", [
    "ada@northbridge.example", "ada@example.com", "linkedin.example.com/in/ada",
    "https://ada.example/portfolio", "ada@school.test",
])
def test_reserved_domains_are_accepted(value):
    GenRequest(applicant_id="applicant0001", **{**IDENTITY, "portfolio": value})


def test_default_school_is_fictional():
    from generator.resume.schema import Education

    school = Education()
    assert "Massachusetts" not in school.school and "Cambridge" not in school.location


def test_printed_github_handle_is_on_a_reserved_domain(applicant):
    spec, _ = generate.build_spec(GenRequest(applicant_id=applicant, **IDENTITY))
    assert spec.github_url == "github.example.com/ada-okonkwo"


def test_help_examples_name_no_real_places():
    for real in ("Massachusetts", "Cambridge", "Boston", "MIT Hacking", "HackMIT", "mit.edu"):
        assert real not in generate.FORMAT


# -- career directions ------------------------------------------------------------------

def _profile_with(applicant_id: str, *skills: str) -> GitHubProfile:
    from generator.schemas import SkillEvidence

    return GitHubProfile(applicant_id=applicant_id, login=applicant_id, html_url="",
                         skill_evidence=[SkillEvidence(skill_id=s, max_strength=0.9)
                                         for s in skills])


def test_directions_spread_evenly_across_families_and_types():
    from collections import Counter

    from generator.resume import careers

    people = [_profile_with(f"applicant{i:04d}", "python", "docker", "sql", "react",
                            "machine-learning", "unit-testing", "flutter", "linux")
              for i in range(45)]
    directions = careers.assign_directions(people)
    families = Counter(d.family for d in directions.values())
    types = Counter(d.creative_type for d in directions.values())
    assert len(families) == len(careers.FAMILIES)
    assert max(families.values()) - min(families.values()) <= 1
    assert max(types.values()) - min(types.values()) <= 1


def test_families_need_supporting_evidence():
    """Nobody is sent toward AI/ML or Mobile without evidence for it."""
    from generator.resume import careers

    people = [_profile_with(f"applicant{i:04d}", "html-css") for i in range(40)]
    families = {d.family for d in careers.assign_directions(people).values()}
    assert "AI / Machine Learning" not in families
    assert "Mobile" not in families
    assert "UI/UX & Design" in families


def test_directions_are_deterministic_regardless_of_order():
    from generator.resume import careers

    people = [_profile_with(f"applicant{i:04d}", "python", "sql") for i in range(12)]
    assert careers.assign_directions(people) == careers.assign_directions(people[::-1])


def test_infoprompt_carries_the_direction_and_the_guide(applicant):
    from generator.resume.careers import Direction

    direction = Direction("Cybersecurity", "D. Cross-Technical", "moves into another discipline")
    block = generate.evidence_block(applicant, direction)
    built = prompt.build(generate.FORMAT, [block], "THE GUIDE TEXT")
    assert "Career direction: Cybersecurity" in built
    assert "THE GUIDE TEXT" in built
    assert "Everything is fictional" in built


@pytest.mark.parametrize(("pasted", "clean"), [
    ("[ada@northbridge.example](mailto:ada@northbridge.example)", "ada@northbridge.example"),
    ("mailto:ada@northbridge.example", "ada@northbridge.example"),
    ("[linkedin.example.com/in/ada](https://linkedin.example.com/in/ada)",
     "linkedin.example.com/in/ada"),
])
def test_markdown_links_from_a_chat_copy_are_unwrapped(pasted, clean):
    field = "email" if "@" in clean else "linkedin"
    request = GenRequest(applicant_id="applicant0001", **{**IDENTITY, field: pasted})
    assert getattr(request, field) == clean


def test_markdown_link_to_a_real_domain_is_still_rejected():
    with pytest.raises(ValueError, match="real domain"):
        GenRequest(applicant_id="applicant0001",
                   **{**IDENTITY, "email": "[ada@gmail.com](mailto:ada@gmail.com)"})


def test_malformed_contact_gets_a_malformed_error_not_a_domain_error():
    with pytest.raises(ValueError, match="not a plain email"):
        GenRequest(applicant_id="applicant0001",
                   **{**IDENTITY, "email": "ada@northbridge.example)"})


def test_prompt_asks_for_a_code_block():
    assert "```bash code block" in prompt.PROMPT


def test_prompt_keeps_its_hard_constraints():
    """The prompt's wording may evolve; these guarantees must survive every edit."""
    text = prompt.PROMPT
    assert "Everything is fictional" in text                     # no real people or places
    assert "reserved domains" in text                            # contact details unreachable
    assert "Technical claims stay inside the evidence" in text   # no accidental exaggeration
    assert "Use only facts shown in the evidence" in text        # project rewrites stay factual
    assert "Never invent senior titles" in text                  # juniors stay junior
    assert "```bash code block" in text                          # survives chat copy-paste
    assert "at most **160 words**" in text                       # fits one page
    assert "at most **9 bullets**" in text
    assert "\\u0027" in text                                     # apostrophes cannot break quoting
    for slot in ("{format}", "{applicants}", "{guide}", "{count}"):
        assert slot in text
