"""Command implementations for the GitHub collection pipeline.

Argument parsing lives in `generator/__main__.py`; these are the handlers.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime

from generator import config
from generator.github import collector, normalize, plan, sampler
from generator.github.client import GitHubClient, RateLimited
from generator.github.skill_map import skill_ids


def _client(args: argparse.Namespace) -> GitHubClient:
    client = GitHubClient(offline=getattr(args, "offline", False))
    mode = "authenticated" if client.authenticated else "UNAUTHENTICATED"
    print(f"[github] {mode} - {client.budget_note()}")
    if not client.authenticated:
        print("[github] 60 req/hour. Set GITHUB_TOKEN in .env for 5000/hour.")
    return client


def cmd_doctor(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        limits = client.get("/rate_limit", max_age=0)
    except Exception as exc:  # noqa: BLE001 - doctor reports any failure, never raises
        print(f"  ! could not reach the API: {exc}")
        return 1
    core = limits["resources"]["core"]
    search = limits["resources"]["search"]
    reset = datetime.fromtimestamp(core["reset"], tz=UTC).isoformat()
    print(f"  core:   {core['remaining']}/{core['limit']} (resets {reset})")
    print(f"  search: {search['remaining']}/{search['limit']}")

    estimate = config.TARGET_PROFILE_COUNT * (config.MAX_REPOS_PER_USER * 7 + 3)
    hours = estimate / core["limit"]
    print(f"  estimated cost of a full cold collect: ~{estimate} requests "
          f"(~{hours:.1f} hours at this limit)")
    print(f"  taxonomy: {len(skill_ids())} skills loaded from {config.TAXONOMY_PATH.name}")
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    client = _client(args)
    unusable = {p.login for p in normalize.load_all_profiles() if not p.usable}
    candidates, consumed = sampler.sample(
        client, target=args.target, per_stratum=args.per_stratum,
        windows_per_run=args.windows, unusable=unusable,
    )
    sampler.save(candidates, consumed)
    print(f"[sample] wrote {config.CANDIDATES_PATH}\n")
    print(plan.render(plan.load_status(args.target)))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Where the corpus stands, per stratum. Reads disk only - no API calls."""
    status = plan.load_status(args.target)
    print(plan.to_json(status) if args.json else plan.render(status))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    if args.logins:
        logins = args.logins
    elif args.all:
        logins = sampler.load_selected()
    else:
        # Only the planned quota per stratum. Reserves are fetched only when a
        # planned profile proves unusable, so requests are not spent on surplus.
        logins = plan.planned_logins(args.target)
    if not logins:
        print("No candidates. Run `sample` first, or pass logins explicitly.")
        return 1

    stratum_by_login = {}
    if config.CANDIDATES_PATH.exists():
        payload = json.loads(config.CANDIDATES_PATH.read_text(encoding="utf-8"))
        stratum_by_login = {c["login"]: c["stratum"] for c in payload.get("candidates", [])}

    already = set(collector.collected_logins())
    todo = [l for l in logins if args.refresh or l not in already]
    scope = "explicit" if args.logins else ("all selected" if args.all else "planned")
    print(f"[collect] {len(logins)} {scope}, {len(already)} already on disk, "
          f"{len(todo)} to fetch\n")

    client = _client(args)
    done, failed = 0, []
    for index, login in enumerate(todo, 1):
        print(f"[{index}/{len(todo)}] {login}", flush=True)
        try:
            collector.collect_user(client, login, max_repos=args.max_repos,
                                   stratum=stratum_by_login.get(login))
            done += 1
        except RateLimited as exc:
            print(f"\n[collect] stopped on rate limit: {exc}")
            print(f"[collect] {done} collected this run. Re-run to resume - nothing is lost.")
            break
        except Exception as exc:  # noqa: BLE001 - one bad user must not abort the run
            print(f"  ! failed: {exc}")
            failed.append(login)

    print(f"\n[collect] done={done} failed={len(failed)} "
          f"total_on_disk={len(collector.collected_logins())}")
    print(f"[collect] api requests this run: {client.request_count}, cache {client.cache.stats()}")
    if failed:
        print(f"[collect] failures: {', '.join(failed)}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    logins = args.logins or collector.collected_logins()
    if not logins:
        print("Nothing collected yet. Run `collect` first.")
        return 1

    built, failed = 0, []
    for login in logins:
        bundle = collector.load_bundle(login)
        if bundle is None:
            failed.append(login)
            continue
        try:
            normalize.save_profile(normalize.build_profile(bundle))
            built += 1
        except Exception as exc:  # noqa: BLE001 - one bad profile must not abort the build
            print(f"  ! {login}: {exc}")
            failed.append(login)

    profiles = normalize.load_all_profiles()
    index = {
        "generated_at": datetime.now(UTC).isoformat(),
        "collector_version": config.COLLECTOR_VERSION,
        "count": len(profiles),
        "profiles": [
            {
                "login": p.login,
                "stratum": p.stratum,
                "html_url": p.html_url,
                "repos_mined": len(p.repos),
                "total_commits": p.total_commits,
                "distinct_skills": len(p.skill_evidence),
                "notes": p.notes,
            }
            for p in profiles
        ],
    }
    config.INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"[build] built {built} profiles, {len(failed)} failed")
    print(f"[build] wrote {config.PROFILES_DIR}/ and {config.INDEX_PATH.name}")
    return 0



def cmd_stats(args: argparse.Namespace) -> int:
    profiles = normalize.load_all_profiles()
    if not profiles:
        print("No profiles built yet.")
        return 1

    all_skills = skill_ids()
    skill_hits: Counter[str] = Counter()
    source_hits: Counter[str] = Counter()
    entry_flags: Counter[str] = Counter()
    intermediate_flags: Counter[str] = Counter()
    repo_count = 0

    for profile in profiles:
        for evidence in profile.skill_evidence:
            skill_hits[evidence.skill_id] += 1
            source_hits.update(evidence.sources)
        for repo in profile.repos:
            repo_count += 1
            for flag, on in repo.structure.get("entry_flags", {}).items():
                if on:
                    entry_flags[flag] += 1
            for flag, on in repo.structure.get("intermediate_flags", {}).items():
                if on:
                    intermediate_flags[flag] += 1

    usable = [p for p in profiles if p.usable]
    print(f"profiles: {len(profiles)} ({len(usable)} usable, "
          f"{len(profiles) - len(usable)} not)   repos mined: {repo_count}")
    print(f"commits attributed: {sum(p.total_commits for p in profiles)}")

    covered = set(skill_hits)
    print(f"\ntaxonomy coverage: {len(covered)}/{len(all_skills)} skills observed "
          f"in at least one profile")
    missing = sorted(all_skills - covered)
    if missing:
        print(f"  never observed ({len(missing)}): {', '.join(missing)}")

    print("\ntop skills by number of profiles:")
    for skill, count in skill_hits.most_common(15):
        print(f"  {count:3d}  {skill}")

    print("\nevidence sources:")
    for source, count in source_hits.most_common():
        print(f"  {count:5d}  {source}")

    print("\nEntry-boundary flags (repos triggering each):")
    for flag, count in entry_flags.most_common():
        print(f"  {count:4d} ({count / repo_count:5.1%})  {flag}")

    print("\nIntermediate countersignals:")
    for flag, count in intermediate_flags.most_common():
        print(f"  {count:4d} ({count / repo_count:5.1%})  {flag}")

    relevance_failures: Counter[str] = Counter()
    relevant_repos = 0
    for profile in profiles:
        for repo in profile.repos:
            if repo.skill_relevant:
                relevant_repos += 1
            else:
                relevance_failures.update(repo.relevance.get("failed", []))
    print(f"\nskill-relevant repos: {relevant_repos}/{repo_count}")
    if relevance_failures:
        print("  why the rest failed (a repo can fail several rules):")
        for rule, count in relevance_failures.most_common():
            print(f"    {count:4d}  {rule}")

    rejected = [p for p in profiles if not p.usable]
    if rejected:
        print("\nunusable profiles:")
        for profile in rejected[:15]:
            print(f"  {profile.login:<22} {profile.usability.get('reason', '')}")

    licences: Counter[str] = Counter()
    unlicensed = 0
    for profile in profiles:
        for repo in profile.repos:
            if repo.license:
                licences[repo.license] += 1
            else:
                unlicensed += 1
    print(f"\nrepo licences ({unlicensed} of {repo_count} carry none):")
    for name, count in licences.most_common(8):
        print(f"  {count:4d}  {name}")

    thin = [p.login for p in profiles if p.notes]
    if thin:
        print(f"\nprofiles with warnings ({len(thin)}): {', '.join(thin[:12])}")
    return 0
