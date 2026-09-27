"""Pure mapping from agent output to resolved skills (no database)."""

from backend.services.skill_resolution import resolve_skills


def claim(name, level, **extra):
    return {"canonical_skill": name, "claimed_level": level, "evidence": [], **extra}


def verdict(skill_id, status, observed, **extra):
    return {"skill_id": skill_id, "status": status, "observed_level": observed, **extra}


def test_levels_follow_resolve_profile_rules():
    skills, unmapped = resolve_skills(
        [claim("Python", 3), claim("Java", 2), claim("Docker", 2), claim("SQL", 2)],
        [
            verdict("python", "verified", 3),
            verdict("java", "partially_verified", 1),
            verdict("docker", "conflicting", 0),
            verdict("sql", "not_observed", None),
        ],
    )
    by_id = {s.skill_id: s for s in skills}
    assert unmapped == []
    assert by_id["python"].final_level == 3 and by_id["python"].flag is None
    assert by_id["java"].final_level == 2  # at most one above observed
    # Contradicted: the lower level wins, down to 0 ("claimed but contradicted").
    assert by_id["docker"].final_level == 0 and by_id["docker"].flag == "conflicting"
    assert by_id["sql"].final_level == 2 and by_id["sql"].flag == "unverified"


def test_without_github_every_claim_stays_unverified():
    skills, _ = resolve_skills([claim("React", 2), claim("TypeScript", 1)], [])
    assert {(s.skill_id, s.final_level, s.flag) for s in skills} == {
        ("react", 2, "unverified"),
        ("typescript", 1, "unverified"),
    }


def test_unknown_names_are_reported_and_spellings_merge_to_the_lower_claim():
    skills, unmapped = resolve_skills(
        [claim("Flight Dynamics", 2), claim("python3", 3), claim("Python", 2)], []
    )
    assert unmapped == ["Flight Dynamics"]
    assert [(s.skill_id, s.claimed_level) for s in skills] == [("python", 2)]


def test_evidence_combines_resume_quotes_and_repositories():
    skills, _ = resolve_skills(
        [claim("Python", 2, evidence=[{"source": "resume", "text": "Built X in Python", "page": 1}])],
        [
            verdict(
                "python",
                "verified",
                2,
                rationale="Supported by 1 repo.",
                repos=[{"repo": "u/x", "html_url": "https://github.com/u/x", "level": 2, "reasons": ["r1"]}],
            )
        ],
    )
    evidence = skills[0].evidence
    assert [(e.source_type, e.reference) for e in evidence] == [
        ("resume", "page 1"),
        ("github", "https://github.com/u/x"),
    ]
    assert skills[0].verification_summary == "Supported by 1 repo."


def test_github_profile_is_reused_from_the_database_snapshot():
    """Reprocessing must not re-scrape GitHub: the DB snapshot is used as-is, no file involved."""
    import json

    from generator.config import PROFILES_DIR
    from generator.schemas import GitHubProfile

    from backend.services.processing import _ensure_github_profile

    snapshot = json.loads((PROFILES_DIR / "applicant0001.json").read_text(encoding="utf-8"))
    snapshot["applicant_id"] = "app-restored"
    applicant = {"id": None, "reference": "app-restored", "github_login": "x", "github_snapshot": snapshot}
    profile, note = _ensure_github_profile(applicant)
    assert note == "using stored GitHub snapshot"
    assert isinstance(profile, GitHubProfile) and profile.applicant_id == "app-restored"

    bare = {"id": None, "reference": "app-none", "github_login": None, "github_snapshot": None}
    assert _ensure_github_profile(bare) == (None, "no GitHub login provided")
