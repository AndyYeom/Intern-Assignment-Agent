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
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from generator.config import CANDIDATES_PATH, TARGET_PROFILE_COUNT
from generator.github.client import GitHubClient, NotFound, RateLimited
from generator.schemas import Candidate

# Strata keep the corpus spread across the taxonomy's categories. Each is a
# GitHub user-search query; the qualifiers encode "student or junior dev".
STRATA: dict[str, str] = {
    "python-backend": "language:Python repos:5..60 followers:2..120",
    "python-data-ml": "language:Jupyter Notebook repos:4..60 followers:1..120",
    "javascript-frontend": "language:JavaScript repos:5..60 followers:2..120",
    "typescript-fullstack": "language:TypeScript repos:5..60 followers:2..120",
    "java-backend": "language:Java repos:4..50 followers:1..100",
    "go-systems": "language:Go repos:4..50 followers:1..100",
    "cpp-systems": "language:C++ repos:4..50 followers:1..100",
    "mobile": "language:Dart repos:3..50 followers:1..100",
    "csharp": "language:C# repos:4..50 followers:1..100",
    # Kotlin, not Rust: every stratum must map onto taxonomy skills, or its
    # profiles fail the usability gate by construction.
    "android-kotlin": "language:Kotlin repos:4..50 followers:1..100",
}

# Inclusion criteria - stated here so they can be quoted in the write-up.
MIN_PUBLIC_REPOS = 4
MAX_PUBLIC_REPOS = 80
MAX_FOLLOWERS = 400          # excludes established devs; we want juniors
MIN_ACCOUNT_AGE_DAYS = 180   # needs enough history to judge
MAX_ACCOUNT_AGE_DAYS = 2600  # ~7 years; older accounts are rarely students


# Extra selected candidates kept per stratum beyond its quota. They replace a
# planned profile that turns out unusable, without another search.
RESERVE_PER_STRATUM = 2


def stratum_quota(target: int, strata_count: int) -> int:
    """How many usable profiles each stratum should contribute to the corpus."""
    return max(1, -(-target // strata_count))


def date_windows(months: int = 6) -> list[tuple[str, str]]:
    """Partition the eligible account-age range into non-overlapping windows.

    This is what makes re-running `sample` productive. GitHub search returns the
    same ordered page for the same query, so without varying the query a second
    run just re-reads the first run's results. Each (stratum, window) pair is a
    distinct slice of the search space, consumed at most once.
    """
    today = datetime.now(UTC).date()
    newest = today - timedelta(days=MIN_ACCOUNT_AGE_DAYS)
    oldest = today - timedelta(days=MAX_ACCOUNT_AGE_DAYS)

    windows: list[tuple[str, str]] = []
    cursor = oldest
    while cursor < newest:
        end = min(cursor + timedelta(days=months * 30), newest)
        windows.append((cursor.isoformat(), end.isoformat()))
        cursor = end
    return windows


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


def load_state() -> dict[str, Any]:
    """Everything previous runs learned: who was seen, which windows are spent."""
    if not CANDIDATES_PATH.exists():
        return {"candidates": [], "consumed": {}}
    payload = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    payload.setdefault("candidates", [])
    payload.setdefault("consumed", {})
    return payload


def sample(
    client: GitHubClient,
    *,
    target: int = TARGET_PROFILE_COUNT,
    per_stratum: int = 12,
    strata: dict[str, str] | None = None,
    windows_per_run: int = 2,
    reserve: int = RESERVE_PER_STRATUM,
    unusable: set[str] | None = None,
) -> tuple[list[Candidate], dict[str, list[int]]]:
    """Top every stratum up to its quota plus a small reserve.

    Additive: skips every login already examined and consumes fresh date
    windows, so each run finds new people. Stratified: each stratum is capped,
    and the emptiest strata are filled first, so no single language can absorb
    the whole target. Candidates whose built profile proved unusable do not
    count towards their stratum, so they get replaced.
    """
    strata = strata or STRATA
    unusable = unusable or set()
    state = load_state()
    consumed: dict[str, list[int]] = {k: list(v) for k, v in state["consumed"].items()}

    existing = [Candidate.model_validate(c) for c in state["candidates"]]
    already_seen = {c.login for c in existing}

    quota = stratum_quota(target, len(strata))
    ceiling = quota + reserve
    live: Counter[str] = Counter(
        c.stratum for c in existing if c.selected and c.login not in unusable
    )

    windows = date_windows()
    now = datetime.now(UTC).isoformat()
    found: list[Candidate] = []

    print(f"[sample] quota {quota} per stratum (+{reserve} reserve) across "
          f"{len(strata)} strata; {len(already_seen)} logins already examined")

    # Emptiest strata first, so a run cut short still spreads across languages.
    for stratum in sorted(strata, key=lambda s: live[s]):
        if live[stratum] >= ceiling:
            continue

        spent = set(consumed.get(stratum, []))
        fresh = [i for i in range(len(windows)) if i not in spent][:windows_per_run]
        if not fresh:
            print(f"[sample] {stratum}: every date window consumed - widen its query")
            continue

        for index in fresh:
            if live[stratum] >= ceiling:
                break
            start_date, end_date = windows[index]
            query = f"{strata[stratum]} created:{start_date}..{end_date}"
            print(f"[sample] {stratum} w{index} ({start_date}..{end_date}) "
                  f"- have {live[stratum]}/{ceiling}")

            try:
                results = client.get(
                    "/search/users",
                    params={"q": query, "sort": "joined", "order": "desc",
                            "per_page": per_stratum},
                    max_age=7 * 24 * 3600,
                )
            except (NotFound, RateLimited) as exc:
                print(f"  ! search failed: {exc}")
                continue

            consumed.setdefault(stratum, []).append(index)

            for item in (results or {}).get("items", []):
                if live[stratum] >= ceiling:
                    break
                login = item.get("login")
                if not login or login in already_seen:
                    continue
                already_seen.add(login)

                try:
                    user = client.get(f"/users/{login}", max_age=7 * 24 * 3600)
                except (NotFound, RateLimited) as exc:
                    print(f"  ! {login}: {exc}")
                    continue

                reason = evaluate(user)
                found.append(Candidate(
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
                ))
                if reason is None:
                    live[stratum] += 1
                    print(f"  + {login} ({user.get('public_repos')} repos)")
                else:
                    print(f"  - {login}: {reason}")

                if not client.authenticated:
                    time.sleep(1.0)

    short = {s: quota - live[s] for s in strata if live[s] < quota}
    if short:
        print("[sample] still short of quota: "
              + ", ".join(f"{s} needs {n}" for s, n in short.items())
              + " - re-run to search more date windows")
    return existing + found, consumed


def save(candidates: list[Candidate], consumed: dict[str, list[int]] | None = None,
         *, strata: dict[str, str] | None = None) -> dict[str, Any]:
    """Persist candidates and the window cursor, so the next run moves on."""
    strata = strata or STRATA
    selected = [c for c in candidates if c.selected]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "method": "GitHub Search API, stratified by language and account-creation window",
        "inclusion_criteria": {
            "min_public_repos": MIN_PUBLIC_REPOS,
            "max_public_repos": MAX_PUBLIC_REPOS,
            "max_followers": MAX_FOLLOWERS,
            "min_account_age_days": MIN_ACCOUNT_AGE_DAYS,
            "max_account_age_days": MAX_ACCOUNT_AGE_DAYS,
        },
        "note": (
            "selected != usable. These are user-level filters; whether a profile "
            "carries enough evidence is decided after collection, in normalize."
        ),
        "strata": strata,
        # Which (stratum, date-window) slices are spent, so re-runs find new people.
        "consumed": consumed or {},
        "windows": date_windows(),
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
