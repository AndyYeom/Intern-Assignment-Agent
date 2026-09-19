"""Tests for the post-collection usability gate and resume de-identification."""
from __future__ import annotations

from generator.github.normalize import assess_usability
from generator.resume.draft import draft
from generator.resume.schema import Education, ResumeInfo
from generator.schemas import GitHubProfile, RepoRecord, SkillEvidence


def _repo(name: str, commits: int, *, fork: bool = False, readme: bool = True,
          relevant: bool = True) -> RepoRecord:
    return RepoRecord(
        name=name, full_name=f"u/{name}", html_url=f"https://github.com/u/{name}",
        is_fork=fork, has_readme=readme, license="MIT",
        commits={"count": commits, "active_days": max(1, commits // 3), "span_days": 120},
        skill_relevant=relevant and not fork,
        relevance={"failed": [] if relevant and not fork else ["not_fork"]},
    )


def _skills(n: int, strength: float = 0.9) -> list[SkillEvidence]:
    return [SkillEvidence(skill_id=f"skill{i}", max_strength=strength) for i in range(n)]


def test_healthy_profile_is_strict():
    tier, report = assess_usability(
        [_repo("a", 30), _repo("b", 25), _repo("c", 10)], _skills(5))
    assert tier == "strict"
    assert report["failed"] == []


def test_profile_of_empty_forks_is_unusable():
    """The sampler's user-level filters cannot catch this; only collection can."""
    repos = [_repo(f"fork{i}", 1, fork=True) for i in range(8)]
    tier, report = assess_usability(repos, _skills(1))
    assert tier == "unusable"
    assert "skill_relevant_repos" in report["failed"]
    assert "total_commits" in report["failed"]


def test_two_relevant_repos_are_not_enough():
    """The floor: three separate pieces of real skill work."""
    repos = [_repo("a", 30), _repo("b", 25), _repo("notes", 40, relevant=False)]
    tier, report = assess_usability(repos, _skills(5))
    assert tier == "unusable"
    assert report["failed"] == ["skill_relevant_repos"]
    assert report["checks"]["skill_relevant_repos"]["actual"] == 2
    assert report["checks"]["skill_relevant_repos"]["tier"] == "relaxed"


def test_few_commits_is_relaxed_not_unusable():
    """Five real repos with 15 commits is thin, not worthless (applicant0033)."""
    repos = [_repo(n, 3) for n in "abcde"]
    tier, report = assess_usability(repos, _skills(5))
    assert tier == "relaxed"
    assert report["failed"] == ["total_commits"]


def test_weak_skill_signals_only_reach_relaxed():
    """Three repo-name guesses are not three verifiable skills."""
    repos = [_repo("a", 30), _repo("b", 25), _repo("c", 20)]
    tier, report = assess_usability(repos, _skills(6, strength=0.2))
    assert tier == "relaxed"
    assert "distinct_skills" in report["failed"]


def test_unreadable_repos_are_unusable():
    repos = [_repo("a", 30, readme=False), _repo("b", 25, readme=False),
             _repo("c", 20, readme=False)]
    tier, report = assess_usability(repos, _skills(5))
    assert tier == "unusable"
    assert "readable_repos" in report["failed"]


def test_usability_report_does_not_duplicate_per_repo_facts():
    """Licences and relevance verdicts live on each repo, not copied into the report."""
    _, report = assess_usability([_repo("a", 30), _repo("b", 25), _repo("c", 20)], _skills(5))
    assert set(report) == {"tier", "checks", "failed", "reason"}


def test_resume_never_carries_the_real_persons_login():
    """A fabricated identity must not link to a real stranger's account."""
    profile = GitHubProfile(
        applicant_id="applicant0001",
        login="realperson42",
        html_url="https://github.com/realperson42",
        repos=[_repo("thing", 20)],
    )
    info = ResumeInfo(github_login="realperson42", first_name="Ada", last_name="Okonkwo",
                      education=Education(major="CS", graduation="2026"))
    spec = draft(profile, info)

    blob = spec.model_dump_json()
    assert "realperson42" not in blob.replace('"github_login":"realperson42"', "")
    # The pseudonymous handle is what the resume shows.
    assert spec.github_url == "github.example.com/ada-okonkwo"
    assert spec.applicant_id == "applicant0001"


def test_profile_schema_cannot_hold_personal_details():
    """Personal fields are not in the schema, so they can never be written."""
    fields = set(GitHubProfile.model_fields)
    assert not fields & {"name", "bio", "company", "location", "blog", "avatar_url", "email"}


def test_personal_details_in_raw_data_are_dropped_by_build():
    from generator.github.normalize import build_profile

    bundle = {
        "user": {"login": "realperson42", "html_url": "https://github.com/realperson42",
                 "name": "Real Name", "bio": "Real bio", "location": "Reykjavik",
                 "blog": "https://realpersonalsite.example", "company": "Acme",
                 "avatar_url": "https://avatars.example/1"},
        "repos": [],
    }
    blob = build_profile(bundle, "applicant0007").model_dump_json()
    for leaked in ("Real Name", "Real bio", "Reykjavik", "realpersonalsite", "Acme", "avatars"):
        assert leaked not in blob


def test_real_login_is_still_retained_for_verification():
    """C must be able to join the resume back to the profile it came from."""
    profile = GitHubProfile(applicant_id="applicant0001", login="realperson42",
                            html_url="https://github.com/realperson42",
                            repos=[_repo("thing", 20)])
    spec = draft(profile, ResumeInfo(github_login="realperson42",
                                     first_name="Ada", last_name="Okonkwo"))
    assert spec.github_login == "realperson42"


def test_scrub_removes_emails_and_phone_numbers_but_not_dates():
    from generator.privacy import scrub

    text = "Contact jane.doe+cv@uni.edu or +1 (617) 555-0142. Released 2024-01-15, v1.2.3."
    cleaned = scrub(text)
    assert "jane.doe" not in cleaned and "555-0142" not in cleaned
    assert "[email]" in cleaned and "[phone]" in cleaned
    assert "2024-01-15" in cleaned and "v1.2.3" in cleaned


def test_profile_readme_repo_keeps_no_excerpt():
    from generator.github.normalize import build_repo

    bundle = {"repo": {"name": "Ada", "full_name": "ada/Ada"},
              "file_contents": {"README.md": "Hi, I'm Ada Lovelace, ada@example.com"}}
    assert build_repo(bundle).readme_excerpt is None


def test_rebuilding_the_same_bundle_is_byte_identical():
    """Time-relative fields are measured from collection, not from build time."""
    from generator.github.normalize import build_profile

    bundle = {"collected_at": "2025-06-01T00:00:00+00:00",
              "user": {"login": "ada", "html_url": "", "created_at": "2022-06-01T00:00:00Z"},
              "repos": []}
    first = build_profile(bundle, "applicant0001").model_dump_json()
    second = build_profile(bundle, "applicant0001").model_dump_json()
    assert first == second
    assert build_profile(bundle, "applicant0001").account_age_days == 1096  # 2024 is a leap year
