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


def test_healthy_profile_is_usable():
    usable, report = assess_usability(
        [_repo("a", 30), _repo("b", 25), _repo("c", 10)], _skills(5))
    assert usable
    assert report["failed"] == []


def test_profile_of_empty_forks_is_rejected():
    """The sampler's user-level filters cannot catch this; only collection can."""
    repos = [_repo(f"fork{i}", 1, fork=True) for i in range(8)]
    usable, report = assess_usability(repos, _skills(1))
    assert not usable
    assert "skill_relevant_repos" in report["failed"]
    assert "total_commits" in report["failed"]


def test_two_relevant_repos_are_not_enough():
    """A profile needs three separate pieces of real skill work."""
    repos = [_repo("a", 30), _repo("b", 25), _repo("notes", 40, relevant=False)]
    usable, report = assess_usability(repos, _skills(5))
    assert not usable
    assert report["failed"] == ["skill_relevant_repos"]
    assert report["checks"]["skill_relevant_repos"] == {"actual": 2, "required": 3}
    assert "notes" in report["not_skill_relevant"]


def test_weak_skill_signals_do_not_count_toward_usability():
    """Three repo-name guesses are not three verifiable skills."""
    repos = [_repo("a", 30), _repo("b", 25), _repo("c", 20)]
    usable, report = assess_usability(repos, _skills(6, strength=0.2))
    assert not usable
    assert "distinct_skills" in report["failed"]


def test_unreadable_repos_are_rejected():
    repos = [_repo("a", 30, readme=False), _repo("b", 25, readme=False),
             _repo("c", 20, readme=False)]
    usable, report = assess_usability(repos, _skills(5))
    assert not usable
    assert "readable_repos" in report["failed"]


def test_usability_report_records_licences():
    _, report = assess_usability([_repo("a", 30), _repo("b", 25), _repo("c", 20)], _skills(5))
    assert report["licenses"] == ["MIT"]
    assert report["unlicensed_repos"] == 0


def test_resume_never_carries_the_real_persons_details():
    """A fabricated identity must not link to a real stranger's account."""
    profile = GitHubProfile(
        login="realperson42",
        name="Real Name",
        bio="Real bio",
        location="Reykjavik, Iceland",
        blog="https://realpersonalsite.example",
        html_url="https://github.com/realperson42",
        repos=[_repo("thing", 20)],
    )
    info = ResumeInfo(github_login="realperson42", first_name="Ada", last_name="Okonkwo",
                      education=Education(major="CS", graduation="2026"))
    spec = draft(profile, info)

    blob = spec.model_dump_json()
    assert "realperson42" not in blob.replace('"github_login":"realperson42"', "")
    assert "Reykjavik" not in blob
    assert "realpersonalsite" not in blob
    assert "Real Name" not in blob
    assert "Real bio" not in blob
    # The pseudonymous handle is what the resume shows.
    assert spec.github_url == "github.com/ada-okonkwo"


def test_real_login_is_still_retained_for_verification():
    """C must be able to join the resume back to the profile it came from."""
    profile = GitHubProfile(login="realperson42", html_url="https://github.com/realperson42",
                            repos=[_repo("thing", 20)])
    spec = draft(profile, ResumeInfo(github_login="realperson42",
                                     first_name="Ada", last_name="Okonkwo"))
    assert spec.github_login == "realperson42"
