"""Tests for commit attribution and error handling in the collector."""
from __future__ import annotations

from typing import Any

import pytest

from generator.github import collector
from generator.github.client import RateLimited


def _commit(i: int, *, author: str | None = None, date: str = "2025-03-01T00:00:00Z") -> dict:
    return {"sha": str(i), "author": {"login": author} if author else None,
            "commit": {"message": f"commit {i}", "author": {"date": date}}}


class FakeClient:
    def __init__(self, *, filtered: list[dict], unfiltered: list[dict],
                 contributors: list[dict], fail_on: str | None = None) -> None:
        self.filtered, self.unfiltered = filtered, unfiltered
        self.contributors, self.fail_on = contributors, fail_on

    def get(self, path: str, *, params: dict[str, Any] | None = None, max_age=None) -> Any:
        if self.fail_on and self.fail_on in path:
            raise RateLimited("simulated transient failure")
        if path.endswith("/contributors"):
            return self.contributors
        if path.endswith("/languages"):
            return {"Python": 5000}
        if "/git/trees/" in path:
            return {"tree": [{"path": "main.py", "type": "blob"}]}
        return []

    def paginate(self, path: str, *, params: dict[str, Any] | None = None, max_pages: int = 5):
        yield from (self.filtered if (params or {}).get("author") else self.unfiltered)

    def file_text(self, *args, **kwargs):
        return None


REPO = {"name": "thing", "full_name": "ada/thing", "default_branch": "main",
        "is_fork": False, "created_at": "2025-01-01T00:00:00Z"}
ANON = {"type": "Anonymous", "contributions": 37}


def _unlinked(n: int, **kwargs) -> list[dict]:
    return [_commit(i, **kwargs) for i in range(n)]


def test_unlinked_email_commits_are_credited_to_a_sole_owner():
    """The bug: 0 commits by author filter on a repo only the owner ever touched."""
    client = FakeClient(filtered=[], unfiltered=_unlinked(37), contributors=[ANON])
    bundle = collector.collect_repo(client, "ada", REPO)
    assert len(bundle["commits"]) == 37
    assert bundle["commit_attribution"] == "sole_author"
    assert bundle["contribution_share"] == 1.0


def test_cloned_tutorial_history_is_not_credited():
    """One linked contributor who is NOT the owner: the tutorial author."""
    tutor = {"type": "User", "login": "tutorial-author", "contributions": 37}
    client = FakeClient(filtered=[], unfiltered=_unlinked(37, author="tutorial-author"),
                        contributors=[tutor])
    bundle = collector.collect_repo(client, "ada", REPO)
    assert bundle["commits"] == []
    assert bundle["commit_attribution"] == "author"
    assert bundle["contribution_share"] == 0.0


def test_imported_history_is_not_credited():
    """Unlinked commits dated long before the repo existed were pushed from elsewhere."""
    old = _unlinked(37, date="2021-06-01T00:00:00Z")
    client = FakeClient(filtered=[], unfiltered=old, contributors=[ANON])
    bundle = collector.collect_repo(client, "ada", REPO)
    assert bundle["commits"] == []
    assert bundle["commit_attribution"] == "refused_imported_history"


def test_commits_by_other_accounts_are_never_credited():
    mixed = _unlinked(5) + [_commit(99, author="someone-else")]
    client = FakeClient(filtered=[], unfiltered=mixed, contributors=[ANON])
    bundle = collector.collect_repo(client, "ada", REPO)
    assert len(bundle["commits"]) == 5


def test_no_fallback_when_two_unlinked_identities_exist():
    client = FakeClient(filtered=[], unfiltered=_unlinked(37), contributors=[ANON, ANON])
    bundle = collector.collect_repo(client, "ada", REPO)
    assert bundle["commit_attribution"] == "author"


def test_no_fallback_on_someone_elses_repo():
    client = FakeClient(filtered=[], unfiltered=_unlinked(37), contributors=[ANON])
    bundle = collector.collect_repo(client, "ada", {**REPO, "full_name": "bob/thing"})
    assert bundle["commit_attribution"] == "author"


def test_team_repo_records_the_persons_share():
    me = {"type": "User", "login": "Ada", "contributions": 10}
    mate = {"type": "User", "login": "bob", "contributions": 30}
    client = FakeClient(filtered=_unlinked(10, author="ada"), unfiltered=[], contributors=[me, mate])
    bundle = collector.collect_repo(client, "ada", REPO)
    assert bundle["contribution_share"] == 0.25


def test_transient_failure_is_raised_not_saved_as_empty_data():
    """A rate-limit hiccup must fail the user, not write a bundle claiming 'no languages'."""
    client = FakeClient(filtered=[], unfiltered=[], contributors=[], fail_on="/languages")
    with pytest.raises(RateLimited):
        collector.collect_repo(client, "ada", REPO)
