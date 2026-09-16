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
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from generator.config import CANDIDATES_PATH
from generator.github.client import GitHubClient, NotFound, RateLimited
from generator.schemas import Candidate
from generator.timeutil import parse_ts

# Strata keep the corpus spread across the taxonomy's categories. Each is a
# GitHub user-search query; the qualifiers encode "student or junior dev".
# Candidates are found through *repository* search: the owners of non-fork repos
# whose primary language is the stratum's. User search (`language:Go` on users)
# matches anyone with any Go repo, forks included, and in practice found people
# who did not write Go at all. Strata with several languages take turns across
# date windows.
REPO_FILTERS = "fork:false size:>=100 stars:0..50"
STRATA: dict[str, list[str]] = {
    "python-backend": ["language:Python"],
    "python-data-ml": ['language:"Jupyter Notebook"'],
    "javascript-frontend": ["language:JavaScript"],
    "typescript-fullstack": ["language:TypeScript"],
    "java-backend": ["language:Java"],
    "go-systems": ["language:Go"],
    "cpp-systems": ["language:C++", "language:C"],
    "mobile": ["language:Dart", "language:Swift"],
    "csharp": ["language:C#"],
    "android-kotlin": ["language:Kotlin"],
}
SEARCH_METHOD = "repositories"

# Inclusion criteria - stated here so they can be quoted in the write-up.
MIN_PUBLIC_REPOS = 4
MAX_PUBLIC_REPOS = 80
MAX_FOLLOWERS = 400          # excludes established devs; we want juniors
MIN_ACCOUNT_AGE_DAYS = 180   # needs enough history to judge
MAX_ACCOUNT_AGE_DAYS = 2600  # ~7 years; older accounts are rarely students


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

    created = parse_ts(user.get("created_at"))
    if created:
        age = (datetime.now(UTC) - created).days
        if age < MIN_ACCOUNT_AGE_DAYS:
            return f"account only {age}d old (min {MIN_ACCOUNT_AGE_DAYS})"
        if age > MAX_ACCOUNT_AGE_DAYS:
            return f"account {age}d old (max {MAX_ACCOUNT_AGE_DAYS})"
    return None


def load_state() -> dict[str, Any]:
    """candidates.json: everyone examined, spent search windows, applicant IDs.

    The only reader of that file. Everything else goes through here.
    """
    if not CANDIDATES_PATH.exists():
        return {"candidates": [], "consumed": {}}
    payload = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    payload.setdefault("candidates", [])
    payload.setdefault("consumed", {})
    return payload


def write_state(state: dict[str, Any]) -> None:
    """The only writer of candidates.json. Atomic."""
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CANDIDATES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(CANDIDATES_PATH)


def windows_for(state: dict[str, Any]) -> list[tuple[str, str]]:
    """The date windows this corpus searches, fixed at the first run.

    `consumed` stores window *indices*. Recomputing windows from today's date
    would shift what index 3 means from one day to the next, silently re-searching
    some ranges and never searching others.
    """
    stored = state.get("windows")
    if stored:
        return [tuple(w) for w in stored]
    return date_windows()


def _queries(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _consumed_key(stratum: str) -> str:
    # Windows spent by the earlier user search do not count against repository
    # search: the same dates, searched a different way, find different people.
    return f"{SEARCH_METHOD}:{stratum}"


def sample(
    client: GitHubClient,
    *,
    wanted: dict[str, int],
    per_stratum: int = 30,
    strata: Mapping[str, str | list[str]] | None = None,
    windows_per_run: int = 6,
) -> tuple[list[Candidate], dict[str, list[int]]]:
    """Find new eligible candidates for the strata that still need them.

    `wanted` maps stratum -> how many new selected candidates to add; it comes
    from slot assignment (plan.CorpusStatus.wanted), so only strata with empty
    slots are searched.

    Additive: every login already examined is skipped, and each run consumes
    fresh repository-creation date windows, so it finds people earlier runs never saw.
    Windows are searched newest first, stopping as soon as a stratum has enough
    people, and at most `windows_per_run` of them per stratum.
    """
    search: Mapping[str, str | list[str]] = strata if strata is not None else STRATA
    state = load_state()
    consumed: dict[str, list[int]] = {k: list(v) for k, v in state["consumed"].items()}

    existing = [Candidate.model_validate(c) for c in state["candidates"]]
    already_seen = {c.login for c in existing}
    added: Counter[str] = Counter()

    windows = windows_for(state)
    now = datetime.now(UTC).isoformat()
    found: list[Candidate] = []

    todo = {s: n for s, n in wanted.items() if n > 0 and s in search}
    if not todo:
        print("[sample] no stratum needs new candidates")
        return existing, consumed
    print(f"[sample] searching {len(todo)} strata: "
          + ", ".join(f"{s} +{n}" for s, n in todo.items())
          + f"; {len(already_seen)} logins already examined")

    # Largest gap first, so a run cut short still helps the emptiest strata.
    for stratum, target in sorted(todo.items(), key=lambda kv: -kv[1]):
        key = _consumed_key(stratum)
        spent = set(consumed.get(key, []))
        # Newest first. The window filters on *repository* creation date, and old
        # repositories belong to long-standing accounts: the first run searched the
        # 2019-2020 windows and rejected nearly everyone as too senior.
        fresh = [i for i in reversed(range(len(windows))) if i not in spent][:windows_per_run]
        if not fresh:
            print(f"[sample] {stratum}: every date window consumed - widen its query")
            continue

        languages = _queries(search[stratum])
        for index in fresh:
            if added[stratum] >= target:
                break
            start_date, end_date = windows[index]
            query = (f"{languages[index % len(languages)]} {REPO_FILTERS} "
                     f"created:{start_date}..{end_date}")
            print(f"[sample] {stratum} w{index} {languages[index % len(languages)]} "
                  f"({start_date}..{end_date}) - added {added[stratum]}/{target}")

            try:
                results = client.get(
                    "/search/repositories",
                    params={"q": query, "sort": "updated", "order": "desc",
                            "per_page": per_stratum},
                    max_age=7 * 24 * 3600,
                )
            except (NotFound, RateLimited) as exc:
                print(f"  ! search failed: {exc}")
                continue

            consumed.setdefault(key, []).append(index)

            for item in (results or {}).get("items", []):
                if added[stratum] >= target:
                    break
                owner = item.get("owner") or {}
                login = owner.get("login")
                if owner.get("type") != "User" or not login or login in already_seen:
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
                    method=SEARCH_METHOD,
                    found_via=item.get("full_name"),
                    discovered_at=now,
                    selected=reason is None,
                    reject_reason=reason,
                    public_repos=user.get("public_repos"),
                    followers=user.get("followers"),
                    account_created_at=user.get("created_at"),
                ))
                if reason is None:
                    added[stratum] += 1
                    print(f"  + {login} ({user.get('public_repos')} repos)")
                else:
                    print(f"  - {login}: {reason}")

                if not client.authenticated:
                    time.sleep(1.0)

    short = {s: n - added[s] for s, n in todo.items() if added[s] < n}
    if short:
        print("[sample] still short: "
              + ", ".join(f"{s} needs {n} more" for s, n in short.items())
              + " - re-run to search more date windows")
    return existing + found, consumed


def save(candidates: list[Candidate], consumed: dict[str, list[int]] | None = None,
         *, strata: Mapping[str, str | list[str]] | None = None) -> None:
    """Persist candidates and the search cursor, so the next run moves on."""
    state = load_state()
    state.update({
        "method": "GitHub Search API, stratified by language and account-creation window",
        "inclusion_criteria": {
            "min_public_repos": MIN_PUBLIC_REPOS,
            "max_public_repos": MAX_PUBLIC_REPOS,
            "max_followers": MAX_FOLLOWERS,
            "min_account_age_days": MIN_ACCOUNT_AGE_DAYS,
            "max_account_age_days": MAX_ACCOUNT_AGE_DAYS,
        },
        "strata": dict(strata if strata is not None else STRATA),
        "search_filters": REPO_FILTERS,
        "windows": [list(w) for w in windows_for(state)],
        "consumed": consumed or {},
        "candidates": [c.model_dump(exclude_none=True) for c in candidates],
    })
    for derived in ("generated_at", "counts", "note"):
        state.pop(derived, None)
    write_state(state)


def load_selected() -> list[str]:
    return [c["login"] for c in load_state()["candidates"] if c.get("selected")]
