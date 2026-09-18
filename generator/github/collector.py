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
from generator.github.client import GitHubClient, NotFound
from generator.github.signals import repo_substance_score
from generator.github.skill_map import MANIFEST_FILES

# Below this many author-matched commits on an owned repo, check whether the
# owner is the sole contributor and their commits simply are not email-linked.
MIN_AUTHOR_FILTERED_COMMITS = 3

# If nearly all the commits credited by the sole-author fallback predate the
# repo's creation on GitHub by more than this, the history was imported (e.g. a
# cloned tutorial pushed to a new repo), and the fallback is refused.
IMPORTED_HISTORY_DAYS = 30
IMPORTED_HISTORY_SHARE = 0.9


def _is_readme(name: str) -> bool:
    return name.lower().split(".")[0] == "readme"


def _write(path_parts: list[str], payload: Any) -> None:
    """Atomic: an interrupted run never leaves a half-written bundle behind."""
    path = RAW_DIR.joinpath(*path_parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(path)


def _slim_commit(commit: dict[str, Any]) -> dict[str, Any]:
    """Only the fields signals.py reads, plus the GitHub login for attribution."""
    node = commit.get("commit") or {}
    return {
        "sha": commit.get("sha"),
        "author_login": (commit.get("author") or {}).get("login"),
        "commit": {"message": node.get("message"),
                   "author": {"date": (node.get("author") or {}).get("date")}},
    }


def _history_imported(commits: list[dict[str, Any]], repo_created_at: str | None) -> bool:
    if not repo_created_at or not commits:
        return False
    created = datetime.fromisoformat(repo_created_at)
    old = 0
    for commit in commits:
        stamp = ((commit.get("commit") or {}).get("author") or {}).get("date")
        if stamp and (created - datetime.fromisoformat(stamp)).days > IMPORTED_HISTORY_DAYS:
            old += 1
    return old / len(commits) >= IMPORTED_HISTORY_SHARE


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

    # Only NotFound (which includes Unavailable and empty repos) means "absent".
    # Anything transient - RateLimited, network errors - propagates, so the user
    # is marked failed and retried, rather than saved as if their repo were empty.
    try:
        bundle["languages"] = client.get(f"/repos/{owner}/{name}/languages")
    except NotFound:
        bundle["languages"] = {}

    # One recursive tree call gives every path in the repo - excellent value for
    # file-based skill detection and for the structure signals.
    tree_paths: list[str] = []
    bundle["tree_truncated"] = False
    try:
        tree = client.get(f"/repos/{owner}/{name}/git/trees/{repo['default_branch']}",
                          params={"recursive": "1"})
        if isinstance(tree, dict):
            bundle["tree_truncated"] = bool(tree.get("truncated"))
            tree_paths = [n["path"] for n in tree.get("tree", []) if n.get("type") == "blob"]
    except NotFound:
        pass
    bundle["tree_paths"] = tree_paths

    # Only this user's commits - the repo may have other contributors.
    commits: list[dict[str, Any]] = []
    try:
        commits = list(client.paginate(
            f"/repos/{owner}/{name}/commits",
            params={"author": login},
            max_pages=MAX_COMMIT_PAGES,
        ))
    except NotFound:
        pass
    attribution = "author"

    # Every contributor, including unlinked (anonymous) email identities, with
    # their commit counts - so a team repo is not credited in full to one member.
    owner_key = login.lower()
    try:
        contributors = client.get(f"/repos/{owner}/{name}/contributors",
                                  params={"per_page": 100, "anon": "1"}) or []
    except NotFound:
        contributors = []
    linked = [c for c in contributors if c.get("type") != "Anonymous"]
    anonymous = [c for c in contributors if c.get("type") == "Anonymous"]
    others = [c for c in linked if (c.get("login") or "").lower() != owner_key]
    total = sum(c.get("contributions", 0) for c in contributors)
    mine = sum(c.get("contributions", 0) for c in linked
               if (c.get("login") or "").lower() == owner_key)
    bundle["contributors_count"] = len(contributors)
    bundle["contribution_share"] = round(mine / total, 3) if total else None

    # The author filter only matches commits made with an email linked to the
    # account, so a student committing from a laptop shows zero commits on their
    # own solo repo. Credit unlinked commits only when it is safe:
    #   * the user owns the repo, and no *other* linked account contributed
    #   * at most one unlinked identity exists (assumed to be the owner)
    #   * only commits with no GitHub author, or the owner as author, are credited
    #   * the history was not imported from elsewhere
    is_owner = owner.lower() == owner_key
    if (is_owner and not repo.get("is_fork") and len(commits) < MIN_AUTHOR_FILTERED_COMMITS
            and not others and len(anonymous) <= 1):
        try:
            unfiltered = list(client.paginate(f"/repos/{owner}/{name}/commits",
                                              max_pages=MAX_COMMIT_PAGES))
        except NotFound:
            unfiltered = []
        credited = [c for c in unfiltered
                    if ((c.get("author") or {}).get("login") or owner_key).lower() == owner_key]
        if len(credited) > len(commits):
            if _history_imported(credited, repo.get("created_at")):
                attribution = "refused_imported_history"
            else:
                commits = credited
                attribution = "sole_author"
                bundle["contribution_share"] = 1.0

    bundle["commit_attribution"] = attribution
    bundle["commits_truncated"] = len(commits) >= MAX_COMMIT_PAGES * 100
    bundle["commits"] = [_slim_commit(c) for c in commits]

    try:
        releases = client.get(f"/repos/{owner}/{name}/releases", params={"per_page": 5})
        bundle["has_releases"] = bool(releases)
    except NotFound:
        bundle["has_releases"] = False

    # Manifests and README - the highest-value file contents.
    root_files = {p for p in tree_paths if "/" not in p}
    wanted = (root_files & MANIFEST_FILES) | {f for f in root_files if _is_readme(f)}
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
    # Own repos only. A fork can never count as skill-relevant, so mining one
    # spends ~7 requests on a slot that cannot contribute evidence.
    # Empty repos (size 0) are skipped too: nothing to read, and every call 409s.
    chosen = [r for r in ranked if not r["is_fork"] and r["size_kb"] > 0][:max_repos]

    bundles = []
    for index, repo in enumerate(chosen, 1):
        print(f"    [{index}/{len(chosen)}] {repo['full_name']}", flush=True)
        bundles.append(collect_repo(client, login, repo))

    # Public events surface PRs to repos the user does not own - the strongest
    # Advanced signal available without authenticated search.
    try:
        events = list(client.paginate(f"/users/{login}/events/public", max_pages=1))
    except NotFound:
        events = []
    # One PR produces several events (opened, closed, ...). Keep one per PR, and
    # mark it merged if any of its events says so.
    external_by_url: dict[str, dict[str, Any]] = {}
    for event in events:
        repo_name = (event.get("repo") or {}).get("name", "")
        if event.get("type") != "PullRequestEvent" or \
                repo_name.lower().startswith(f"{login.lower()}/"):
            continue
        pr = (event.get("payload") or {}).get("pull_request") or {}
        url = pr.get("html_url")
        if not url:
            continue
        entry = external_by_url.setdefault(url, {
            "repo": repo_name, "html_url": url, "title": pr.get("title"),
            "state": pr.get("state"), "merged": False, "created_at": event.get("created_at"),
        })
        entry["merged"] = entry["merged"] or bool(pr.get("merged_at"))
        if pr.get("state") == "closed":
            entry["state"] = "closed"
    external = list(external_by_url.values())

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
