"""Tests for the evidence agent - observed levels, statuses and claim parsing."""
from __future__ import annotations

import pytest

from generator.schemas import GitHubProfile, RepoRecord
from src.evidence_agent.claims import parse_skill
from src.evidence_agent.evidence_models import ApplicantProfile, SkillClaim
from src.evidence_agent.observe import observe
from src.evidence_agent.verify import verify

SIGNAL = {"skill_id": "python", "source": "language", "detail": "Python: 40,000 bytes",
          "strength": 1.0}


def _repo(name: str, **overrides) -> RepoRecord:
    base = {
        "name": name, "full_name": f"u/{name}", "html_url": f"https://github.com/u/{name}",
        "commits": {"count": 40},
        "structure": {"entry_flags": {}, "intermediate_flags": {"has_tests": True,
                                                                 "multi_month_span": True}},
        "judgment": {"commit_message_kinds": {"fix": 0}},
        "skill_signals": [SIGNAL],
    }
    base.update(overrides)
    return RepoRecord(**base)


def _profile(*repos: RepoRecord) -> GitHubProfile:
    return GitHubProfile(applicant_id="applicant0001", login="u",
                         html_url="https://github.com/u", repos=list(repos))


def _claims(level: int, skill_id: str = "python") -> ApplicantProfile:
    return ApplicantProfile(applicant_id="applicant0001",
                            skills=[SkillClaim(skill_id=skill_id, level=level)])


def test_independent_work_is_intermediate():
    assert observe(_profile(_repo("api")), "python").level == 2


def test_notebook_only_is_entry():
    """The task's own example: "proficient in Python", commits are notebooks only."""
    notebook = _repo("nb", structure={"entry_flags": {"notebook_only": True},
                                      "intermediate_flags": {"has_tests": True}})
    assert observe(_profile(notebook), "python").level == 1
    assert verify(_claims(3), _profile(notebook)).skills[0].status == "conflicting"


def test_others_depending_is_advanced():
    repo = _repo("lib", judgment={"others_depend": True})
    report = verify(_claims(3), _profile(repo))
    assert report.skills[0].status == "verified"
    assert report.skills[0].repo_links == ["https://github.com/u/lib"]


def test_one_level_short_is_partial():
    assert verify(_claims(3), _profile(_repo("api"))).skills[0].status == "partially_verified"


def test_absence_is_not_observed_not_conflicting():
    report = verify(_claims(3, "kubernetes"), _profile(_repo("api")))
    assert report.skills[0].status == "not_observed"
    assert report.skills[0].observed_level is None


def test_repo_name_alone_is_not_evidence():
    weak = _repo("py", skill_signals=[{**SIGNAL, "source": "repo_name", "strength": 0.2}])
    assert observe(_profile(weak), "python").level is None


def test_unclaimed_skills_are_reported_not_penalised():
    report = verify(_claims(1, "kubernetes"), _profile(_repo("api")))
    assert [s.skill_id for s in report.unclaimed_observed] == ["python"]


def test_mismatched_pair_is_refused():
    other = ApplicantProfile(applicant_id="applicant0002")
    with pytest.raises(ValueError):
        verify(other, _profile())


def test_parenthetical_names_are_not_levels():
    assert parse_skill("Python (Advanced)") == ("Python", 3)
    assert parse_skill("Data Analysis (pandas)") == ("Data Analysis (pandas)", None)
