"""Stage 2: fetch raw GitHub payloads for each selected user.

This is the only expensive stage, so it does as little thinking as possible -
it stores what the API returned, verbatim, under data/githubs/raw/<login>/.
All interpretation happens in normalize.py, which needs no network and can be
re-run for free every time the schema changes.

Budget per repo: ~5 requests (languages, tree, commits, contributors, manifests).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from generator.config import MAX_COMMIT_PAGES, MAX_REPOS_PER_USER, RAW_DIR
from generator.github.client import GitHubClient, NotFound, RateLimited
from generator.github.signals import repo_substance_score
from generator.github.skill_map import MANIFEST_FILES

# Below this many author-matched commits on an owned repo, check whether the
# owner is the sole contributor and their commits simply are not email-linked.
MIN_AUTHOR_FILTERED_COMMITS = 3

# Files worth pulling the contents of, beyond manifests.
NOTABLE_ROOT_FILES = {"README.md", "README.rst", "README.txt", "readme.md"}


def _write(path_parts: list[str], payload: Any) -> None:
    path = RAW_DIR.joinpath(*path_parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _repo_summary(repo: dict[str, Any]) -> dict[str, Any]:
    """The subset of the repo object we actually use, for ranking and storage."""
    return {
        "name": repo.get("name"),
        "full_name": repo.get("full_name"),
        "owner": (repo.get("owner") or {}).get("login"),
        "language": repo.get("language"),
        "html_url": repo.get("html_url"),
        "description": repo.get("description"),
        "homepage": repo.get("homepage"),
        "is_fork": repo.get("fork", False),
        "is_archived": repo.get("archived", False),
        "is_template": repo.get("is_template", False),
        "created_at": repo.get("created_at"),
        "pushed_at": repo.get("pushed_at"),
        "updated_at": repo.get("updated_at"),
        "stargazers": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "size_kb": repo.get("size", 0),
        "default_branch": repo.get("default_branch") or "main",
        "license": (repo.get("license") or {}).get("spdx_id"),
        "topics": repo.get("topics") or [],
        "has_issues": repo.get("has_issues", False),
    }


def collect_repo(client: GitHubClient, login: str, repo: dict[str, Any]) -> dict[str, Any]:
    """Fetch everything we need about one repo. Each call is individually cached."""
    owner = repo["full_name"].split("/")[0]
    name = repo["name"]
    bundle: dict[str, Any] = {"repo": repo}

    try:
        bundle["languages"] = client.get(f"/repos/{owner}/{name}/languages")
    except (NotFound, RateLimited):
        bundle["languages"] = {}

    # One recursive tree call gives every path in the repo - excellent value for
    # file-based skill detection and for the structure signals.
    tree_paths: list[str] = []
    try:
        tree = client.get(f"/repos/{owner}/{name}/git/trees/{repo['default_branch']}",
                          params={"recursive": "1"})
        bundle["tree_truncated"] = bool((tree or {}).get("truncated"))
        tree_paths = [n["path"] for n in (tree or {}).get("tree", []) if n.get("type") == "blob"]
    except (NotFound, RateLimited):
        bundle["tree_truncated"] = False
    bundle["tree_paths"] = tree_paths

    # Only this user's commits - the repo may have other contributors.
    commits: list[dict[str, Any]] = []
    try:
        commits = list(client.paginate(
            f"/repos/{owner}/{name}/commits",
            params={"author": login},
            max_pages=MAX_COMMIT_PAGES,
        ))
    except (NotFound, RateLimited):
        pass
    bundle["commit_attribution"] = "author"

    try:
        contributors = client.get(f"/repos/{owner}/{name}/contributors", params={"per_page": 30})
        bundle["contributors_count"] = len(contributors or [])
    except (NotFound, RateLimited):
        bundle["contributors_count"] = 1

    # The author filter only matches commits made with an email linked to the
    # account. Someone committing from a laptop with another email shows zero
    # commits on their own solo repo. When the owner is provably the only
    # contributor - counting unlinked (anonymous) ones - every commit is theirs.
    is_owner = owner.lower() == login.lower()
    if is_owner and not repo.get("is_fork") and len(commits) < MIN_AUTHOR_FILTERED_COMMITS:
        try:
            everyone = client.get(f"/repos/{owner}/{name}/contributors",
                                  params={"per_page": 30, "anon": "1"})
            if len(everyone or []) <= 1:
                unfiltered = list(client.paginate(f"/repos/{owner}/{name}/commits",
                                                  max_pages=MAX_COMMIT_PAGES))
                if len(unfiltered) > len(commits):
                    commits = unfiltered
                    bundle["commit_attribution"] = "sole_author"
        except (NotFound, RateLimited):
            pass

    # Store only the fields signals.py reads, so raw/ stays a manageable size.
    bundle["commits"] = [
        {"commit": {"message": (c.get("commit") or {}).get("message"),
                    "author": {"date": ((c.get("commit") or {}).get("author") or {}).get("date")}},
         "sha": c.get("sha")}
        for c in commits
    ]

    try:
        releases = client.get(f"/repos/{owner}/{name}/releases", params={"per_page": 5})
        bundle["has_releases"] = bool(releases)
    except (NotFound, RateLimited):
        bundle["has_releases"] = False

    # Manifests and README - the highest-value file contents.
    root_files = {p for p in tree_paths if "/" not in p}
    wanted = (root_files & MANIFEST_FILES) | (root_files & NOTABLE_ROOT_FILES)
    contents: dict[str, str] = {}
    for path in sorted(wanted):
        text = client.file_text(owner, name, path)
        if text:
            contents[path] = text[:60_000]
    bundle["file_contents"] = contents

    return bundle


def collect_user(client: GitHubClient, login: str, *, max_repos: int = MAX_REPOS_PER_USER,
                 stratum: str | None = None) -> dict[str, Any]:
    """Fetch one user's profile, ranked repos, and recent external activity."""
    user = client.get(f"/users/{login}")
    # Never persist a public email - see the provenance note in data/githubs/.
    user.pop("email", None)

    # One page (100) covers everyone: the sampler rejects accounts with more than
    # 80 public repos. The full list is needed to rank, even though only a few are mined.
    repos_raw = list(client.paginate(f"/users/{login}/repos",
                                     params={"type": "owner", "sort": "pushed"}, max_pages=1))
    summaries = [_repo_summary(r) for r in repos_raw]

    # Rank by substance, then cap - so the budget goes to the interesting repos.
    ranked = sorted(summaries, key=repo_substance_score, reverse=True)
    chosen = [r for r in ranked if not r["is_fork"]][:max_repos]
    if len(chosen) < max_repos:
        chosen += [r for r in ranked if r["is_fork"]][: max_repos - len(chosen)]

    bundles = []
    for index, repo in enumerate(chosen, 1):
        print(f"    [{index}/{len(chosen)}] {repo['full_name']}", flush=True)
        bundles.append(collect_repo(client, login, repo))

    # Public events surface PRs to repos the user does not own - the strongest
    # Advanced signal available without authenticated search.
    try:
        events = list(client.paginate(f"/users/{login}/events/public", max_pages=1))
    except (NotFound, RateLimited):
        events = []
    external = [
        {
            "repo": e["repo"]["name"],
            "html_url": ((e.get("payload") or {}).get("pull_request") or {}).get("html_url", ""),
            "title": ((e.get("payload") or {}).get("pull_request") or {}).get("title"),
            "state": ((e.get("payload") or {}).get("pull_request") or {}).get("state"),
            "merged": bool(((e.get("payload") or {}).get("pull_request") or {}).get("merged_at")),
            "created_at": e.get("created_at"),
        }
        for e in events
        if e.get("type") == "PullRequestEvent"
        and not e.get("repo", {}).get("name", "").startswith(f"{login}/")
    ]

    payload = {
        "login": login,
        "stratum": stratum,
        "collected_at": datetime.now(UTC).isoformat(),
        "user": user,
        "repo_count_total": len(summaries),
        "repos": bundles,
        "external_contributions": external,
    }
    _write([login, "bundle.json"], payload)
    return payload


def load_bundle(login: str) -> dict[str, Any] | None:
    path = RAW_DIR / login / "bundle.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def collected_logins() -> list[str]:
    if not RAW_DIR.exists():
        return []
    return sorted(p.name for p in RAW_DIR.iterdir() if (p / "bundle.json").exists())
