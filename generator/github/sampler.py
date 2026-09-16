"""Select the corpus of student / junior-dev profiles via the GitHub Search API.

Programmatic selection rather than a hand-picked list, for three reasons:
  * it is reproducible - candidates.json records the exact queries used
  * it is stratified - the corpus spans the taxonomy instead of being 40 Python people
  * the inclusion criteria can be stated in the write-up as a sampling method

Search endpoints have their own tighter rate limit (10/min unauthenticated,
30/min with a token), so this stage is deliberately small and heavily cached.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from generator.config import CANDIDATES_PATH, TARGET_PROFILE_COUNT
from generator.github.client import GitHubClient, NotFound, RateLimited
from generator.schemas import Candidate

# Strata keep the corpus spread across the taxonomy's categories. Each is a
# GitHub user-search query; the qualifiers encode "student or junior dev".
STRATA: dict[str, str] = {
    "python-backend": "language:Python repos:5..60 followers:2..120 created:>2020-01-01",
    "python-data-ml": "language:Jupyter Notebook repos:4..60 followers:1..120 created:>2020-01-01",
    "javascript-frontend": "language:JavaScript repos:5..60 followers:2..120 created:>2020-01-01",
    "typescript-fullstack": "language:TypeScript repos:5..60 followers:2..120 created:>2020-06-01",
    "java-backend": "language:Java repos:4..50 followers:1..100 created:>2020-01-01",
    "go-systems": "language:Go repos:4..50 followers:1..100 created:>2020-01-01",
    "cpp-systems": "language:C++ repos:4..50 followers:1..100 created:>2020-01-01",
    "mobile": "language:Dart repos:3..50 followers:1..100 created:>2020-01-01",
    "csharp": "language:C# repos:4..50 followers:1..100 created:>2020-01-01",
    "students-bio": "language:Python repos:5..60 followers:1..60 created:>2021-06-01",
}

# Inclusion criteria - stated here so they can be quoted in the write-up.
MIN_PUBLIC_REPOS = 4
MAX_PUBLIC_REPOS = 80
MAX_FOLLOWERS = 400          # excludes established devs; we want juniors
MIN_ACCOUNT_AGE_DAYS = 180   # needs enough history to judge
MAX_ACCOUNT_AGE_DAYS = 2600  # ~7 years; older accounts are rarely students


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def evaluate(user: dict[str, Any]) -> str | None:
    """Return a rejection reason, or None if the user is eligible."""
    repos = user.get("public_repos", 0)
    if repos < MIN_PUBLIC_REPOS:
        return f"only {repos} public repos (min {MIN_PUBLIC_REPOS})"
    if repos > MAX_PUBLIC_REPOS:
        return f"{repos} public repos (max {MAX_PUBLIC_REPOS}) - likely not a junior"
    if user.get("followers", 0) > MAX_FOLLOWERS:
        return f"{user['followers']} followers (max {MAX_FOLLOWERS}) - established dev"
    if user.get("type") != "User":
        return f"account type {user.get('type')}"

    created = _parse_ts(user.get("created_at"))
    if created:
        age = (datetime.now(UTC) - created).days
        if age < MIN_ACCOUNT_AGE_DAYS:
            return f"account only {age}d old (min {MIN_ACCOUNT_AGE_DAYS})"
        if age > MAX_ACCOUNT_AGE_DAYS:
            return f"account {age}d old (max {MAX_ACCOUNT_AGE_DAYS})"
    return None


def sample(
    client: GitHubClient,
    *,
    target: int = TARGET_PROFILE_COUNT,
    per_stratum: int = 12,
    strata: dict[str, str] | None = None,
) -> list[Candidate]:
    """Walk the strata, verify each hit against the inclusion criteria, stop at target."""
    strata = strata or STRATA
    per_target = max(1, -(-target // len(strata)))  # ceil, for an even spread
    now = datetime.now(UTC).isoformat()

    candidates: list[Candidate] = []
    seen: set[str] = set()
    selected_by_stratum: dict[str, int] = {key: 0 for key in strata}

    for stratum, query in strata.items():
        print(f"[sample] {stratum}: {query}", flush=True)
        try:
            results = client.get(
                "/search/users",
                params={"q": query, "sort": "joined", "order": "desc", "per_page": per_stratum},
                max_age=7 * 24 * 3600,
            )
        except (NotFound, RateLimited) as exc:
            print(f"  ! search failed: {exc}", flush=True)
            continue

        for item in (results or {}).get("items", []):
            login = item.get("login")
            if not login or login in seen:
                continue
            seen.add(login)

            if selected_by_stratum[stratum] >= per_target:
                break

            try:
                user = client.get(f"/users/{login}", max_age=7 * 24 * 3600)
            except (NotFound, RateLimited) as exc:
                print(f"  ! {login}: {exc}", flush=True)
                continue

            reason = evaluate(user)
            candidate = Candidate(
                login=login,
                html_url=user.get("html_url", f"https://github.com/{login}"),
                stratum=stratum,
                query=query,
                discovered_at=now,
                selected=reason is None,
                reject_reason=reason,
                public_repos=user.get("public_repos"),
                followers=user.get("followers"),
                account_created_at=user.get("created_at"),
            )
            candidates.append(candidate)
            if reason is None:
                selected_by_stratum[stratum] += 1
                print(f"  + {login} ({user.get('public_repos')} repos)", flush=True)
            else:
                print(f"  - {login}: {reason}", flush=True)

            # Search is the tightest limit on the unauthenticated path.
            if not client.authenticated:
                time.sleep(1.0)

        if sum(selected_by_stratum.values()) >= target:
            break

    return candidates


def save(candidates: list[Candidate], *, strata: dict[str, str] | None = None) -> dict[str, Any]:
    strata = strata or STRATA
    selected = [c for c in candidates if c.selected]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "method": "GitHub Search API, stratified by primary language",
        "inclusion_criteria": {
            "min_public_repos": MIN_PUBLIC_REPOS,
            "max_public_repos": MAX_PUBLIC_REPOS,
            "max_followers": MAX_FOLLOWERS,
            "min_account_age_days": MIN_ACCOUNT_AGE_DAYS,
            "max_account_age_days": MAX_ACCOUNT_AGE_DAYS,
        },
        "strata": strata,
        "counts": {
            "examined": len(candidates),
            "selected": len(selected),
            "rejected": len(candidates) - len(selected),
        },
        "candidates": [c.model_dump() for c in candidates],
    }
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_selected() -> list[str]:
    if not CANDIDATES_PATH.exists():
        return []
    payload = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    return [c["login"] for c in payload.get("candidates", []) if c.get("selected")]
