"""Tests for commit attribution in the collector."""
from __future__ import annotations

from typing import Any

from generator.github import collector


def _commit(message: str) -> dict[str, Any]:
    return {"sha": message, "commit": {"message": message,
                                       "author": {"date": "2025-01-01T00:00:00Z"}}}


class FakeClient:
    def __init__(self, *, filtered: int, unfiltered: int, anon_contributors: int) -> None:
        self.filtered = filtered
        self.unfiltered = unfiltered
        self.anon_contributors = anon_contributors

    def get(self, path: str, *, params: dict[str, Any] | None = None, max_age=None) -> Any:
        params = params or {}
        if path.endswith("/contributors"):
            count = self.anon_contributors if params.get("anon") else 0
            return [{"login": f"c{i}"} for i in range(count)]
        if path.endswith("/languages"):
            return {"Python": 5000}
        if "/git/trees/" in path:
            return {"tree": [{"path": "main.py", "type": "blob"}]}
        return []

    def paginate(self, path: str, *, params: dict[str, Any] | None = None, max_pages: int = 5):
        n = self.filtered if (params or {}).get("author") else self.unfiltered
        yield from (_commit(f"commit {i}") for i in range(n))

    def file_text(self, *args, **kwargs):
        return None


REPO = {"name": "thing", "full_name": "ada/thing", "default_branch": "main", "is_fork": False}


def test_unlinked_email_commits_are_attributed_to_a_sole_owner():
    """The bug: 0 commits by author filter on a repo only the owner ever touched."""
    client = FakeClient(filtered=0, unfiltered=37, anon_contributors=1)
    bundle = collector.collect_repo(client, "ada", REPO)
    assert len(bundle["commits"]) == 37
    assert bundle["commit_attribution"] == "sole_author"


def test_no_fallback_when_others_contributed():
    """With a second contributor, unfiltered commits are not all the owner's."""
    client = FakeClient(filtered=0, unfiltered=37, anon_contributors=2)
    bundle = collector.collect_repo(client, "ada", REPO)
    assert len(bundle["commits"]) == 0
    assert bundle["commit_attribution"] == "author"


def test_no_fallback_on_someone_elses_repo():
    client = FakeClient(filtered=0, unfiltered=37, anon_contributors=1)
    bundle = collector.collect_repo(client, "ada", {**REPO, "full_name": "bob/thing"})
    assert bundle["commit_attribution"] == "author"


def test_no_fallback_when_author_filter_already_works():
    client = FakeClient(filtered=12, unfiltered=15, anon_contributors=1)
    bundle = collector.collect_repo(client, "ada", REPO)
    assert len(bundle["commits"]) == 12
    assert bundle["commit_attribution"] == "author"
