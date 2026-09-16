"""Tests for the proficiency-boundary heuristics in signals.py.

These encode the two decisive questions from data/proficiency_levels.md.
"""
from __future__ import annotations

from itertools import pairwise

from generator.github import signals


def _commits(pairs):
    return [{"commit": {"message": m, "author": {"date": d}}} for m, d in pairs]


def test_tutorial_repo_reads_as_entry():
    repo = {"name": "netflix-clone", "description": "built following a YouTube tutorial",
            "is_fork": True}
    summary = signals.commit_stats(_commits([("initial commit", "2025-01-05T10:00:00Z")]))
    result = signals.structure_signals(repo, ["app.js"], summary, None)

    flags = result["entry_flags"]
    assert flags["is_fork"] and flags["tutorial_name_hit"] and flags["single_commit"]
    assert flags["no_readme"] and flags["follow_along_phrase"]
    assert result["intermediate_flag_count"] == 0


def test_self_directed_repo_reads_as_intermediate():
    repo = {"name": "ferry-timetable-api", "description": "schedule API for the island ferry",
            "homepage": "https://ferry.example.com", "license": "MIT",
            "has_ci": True, "has_tests": True, "has_docker": True, "stargazers": 7}
    summary = signals.commit_stats(_commits([
        (f"feature {i}", f"2025-0{1 + i % 6}-1{i % 9}T10:00:00Z") for i in range(14)
    ]))
    paths = [f"src/mod{i}.py" for i in range(10)] + [".github/workflows/ci.yml", "Dockerfile"]
    result = signals.structure_signals(repo, paths, summary, "x" * 1500)

    assert result["intermediate_flag_count"] >= 6
    assert not result["entry_flags"]["tutorial_name_hit"]
    assert not result["entry_flags"]["is_fork"]


def test_notebook_only_repo_is_flagged():
    repo = {"name": "data-analysis"}
    summary = signals.commit_stats(_commits([("add notebook", "2025-03-01T10:00:00Z")]))
    result = signals.structure_signals(repo, ["eda.ipynb", "model.ipynb"], summary, None)
    assert result["entry_flags"]["notebook_only"]
    assert result["notebook_count"] == 2


def test_long_span_with_few_active_days_is_not_sustained():
    """Two bursts two years apart is not multi-month work."""
    summary = signals.commit_stats(_commits([
        ("start", "2023-01-01T10:00:00Z"),
        ("more", "2023-01-02T10:00:00Z"),
        ("revive", "2025-06-01T10:00:00Z"),
    ]))
    assert summary["span_days"] > 800
    assert summary["active_days"] == 3
    result = signals.structure_signals({"name": "x"}, [], summary, None)
    assert not result["intermediate_flags"]["multi_month_span"]


def test_judgment_signals_read_commit_messages():
    summary = signals.commit_stats(_commits([
        ("fix race condition in the websocket reconnect", "2025-01-01T10:00:00Z"),
        ("optimise query - was doing N+1", "2025-02-01T10:00:00Z"),
        ("refactor auth into middleware", "2025-03-01T10:00:00Z"),
        ("update", "2025-04-01T10:00:00Z"),
    ]))
    result = signals.judgment_signals(summary, {"stargazers": 5})
    kinds = result["commit_message_kinds"]
    assert kinds["fix"] >= 1 and kinds["perf"] >= 1 and kinds["refactor"] >= 1
    assert result["others_depend"]


def test_low_effort_commit_messages_are_measured():
    summary = signals.commit_stats(_commits([
        ("update", "2025-01-01T10:00:00Z"), ("update", "2025-01-02T10:00:00Z"),
        ("wip", "2025-01-03T10:00:00Z"), ("changes", "2025-01-04T10:00:00Z"),
        ("add caching layer for the tile server", "2025-01-05T10:00:00Z"),
    ]))
    assert summary["low_effort_message_ratio"] >= 0.7


def test_no_signal_ever_subtracts():
    """proficiency_levels.md: absence of evidence is never a reduction."""
    empty = signals.commit_stats([])
    result = signals.structure_signals({"name": "x"}, [], empty, None)
    assert result["entry_flag_count"] >= 0
    assert result["intermediate_flag_count"] == 0
    assert all(isinstance(v, bool) for v in result["entry_flags"].values())


def test_forks_rank_below_original_work():
    fork = {"name": "a", "is_fork": True, "stargazers": 500, "size_kb": 9000}
    original = {"name": "b", "is_fork": False, "size_kb": 300, "description": "d"}
    assert signals.repo_substance_score(original) > signals.repo_substance_score(fork)


def test_date_windows_partition_without_overlap():
    """Overlapping windows would re-surface people an earlier run already saw."""
    from generator.github.sampler import date_windows

    windows = date_windows()
    assert len(windows) > 5
    for (_, end), (next_start, _) in pairwise(windows):
        assert end == next_start, "windows must tile, not overlap or gap"
