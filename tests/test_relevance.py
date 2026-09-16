"""Tests for the per-repo skill-relevance rule in signals.py."""
from __future__ import annotations

import pytest

from generator.github.signals import (
    is_non_project_name,
    repo_substance_score,
    skill_relevance,
)

STRONG_PYTHON = [{"skill_id": "python", "source": "language", "strength": 1.0}]


def _check(**overrides):
    args = {
        "name": "ferry-api",
        "owner": "ada",
        "is_fork": False,
        "languages": {"Python": 40_000},
        "structure": {"code_file_count": 12, "notebook_count": 0},
        "commit_count": 25,
        "skill_signals": STRONG_PYTHON,
    }
    args.update(overrides)
    return skill_relevance(**args)


def test_real_project_is_relevant():
    relevant, report = _check()
    assert relevant
    assert report["failed"] == []
    assert report["strong_skills"] == ["python"]


@pytest.mark.parametrize("name", [
    "dotfiles", "my-dotfiles", "notes", "lecture-notes", "awesome-python",
    "resume", "my-cv", "python-cheatsheet", "interview-prep", ".github",
    "reading-list", "config",
])
def test_non_project_names_are_rejected(name):
    relevant, report = _check(name=name)
    assert not relevant
    assert "project_name" in report["failed"]


@pytest.mark.parametrize("name", [
    "ferry-api", "notebook-search-engine-app", "config-parser-rs", "note-taking-app",
    "resume-parser", "env-loader", "books-api", "setup-wizard-cli",
])
def test_projects_that_start_with_a_keyword_still_pass(name):
    """Only a name that *ends* in the keyword marks a non-project."""
    assert not is_non_project_name(name, "ada")


@pytest.mark.parametrize("name", ["cs50-notes", "nvim-config", "system-design-roadmap"])
def test_names_ending_in_a_keyword_are_non_projects(name):
    assert is_non_project_name(name, "ada")


def test_profile_readme_repo_is_rejected():
    relevant, report = _check(name="Ada", owner="ada")
    assert not relevant
    assert "project_name" in report["failed"]


def test_markdown_only_repo_is_rejected_however_large():
    """Markdown is not a taxonomy language, so a big notes repo scores zero bytes."""
    relevant, report = _check(
        name="ml-study",
        languages={"Markdown": 900_000, "TeX": 200_000},
        structure={"code_file_count": 0, "notebook_count": 0},
        skill_signals=[],
    )
    assert not relevant
    assert {"has_code_files", "code_bytes", "strong_skill_signal"} <= set(report["failed"])
    assert report["code_bytes"] == 0


def test_notebook_project_counts_as_code():
    relevant, _ = _check(
        languages={"Jupyter Notebook": 80_000},
        structure={"code_file_count": 0, "notebook_count": 3},
    )
    assert relevant


def test_only_weak_signals_fail():
    """A topic or a word in the repo name is not evidence of a skill."""
    relevant, report = _check(skill_signals=[
        {"skill_id": "react", "source": "topic", "strength": 0.3},
        {"skill_id": "python", "source": "repo_name", "strength": 0.2},
    ])
    assert not relevant
    assert report["failed"] == ["strong_skill_signal"]


def test_fork_and_no_commits_fail():
    relevant, report = _check(is_fork=True, commit_count=0)
    assert not relevant
    assert {"not_fork", "own_commits"} <= set(report["failed"])


def test_ranking_sinks_non_projects_below_real_repos():
    real = {"name": "ferry-api", "owner": "ada", "language": "Python", "size_kb": 10}
    notes = {"name": "notes", "owner": "ada", "language": "Python", "size_kb": 9000}
    textonly = {"name": "ml-study", "owner": "ada", "language": None, "size_kb": 9000}
    fork = {"name": "react", "owner": "ada", "language": "JavaScript", "is_fork": True}

    assert repo_substance_score(real) > repo_substance_score(textonly)
    assert repo_substance_score(textonly) > repo_substance_score(notes)
    assert repo_substance_score(notes) > repo_substance_score(fork)


def test_single_file_project_is_still_skill_work():
    """40 KB of JavaScript in one file is Entry-level work, not random text."""
    relevant, _ = _check(
        languages={"JavaScript": 40_000},
        structure={"code_file_count": 1, "notebook_count": 0},
        skill_signals=[{"skill_id": "javascript", "source": "language", "strength": 1.0}],
        commit_count=1,
    )
    assert relevant


def test_single_notebook_analysis_is_still_skill_work():
    """An 'only notebooks' profile is the exaggeration case C must catch - keep it."""
    relevant, _ = _check(
        languages={"Jupyter Notebook": 2_500_000},
        structure={"code_file_count": 0, "notebook_count": 1},
    )
    assert relevant


def test_tiny_repo_is_still_rejected():
    relevant, report = _check(
        languages={"Python": 300},
        structure={"code_file_count": 1, "notebook_count": 0},
    )
    assert not relevant
    assert report["failed"] == ["code_bytes"]


def test_web_files_count_as_code():
    from generator.github.signals import CODE_EXTS

    assert {".html", ".css", ".sql"} <= CODE_EXTS
