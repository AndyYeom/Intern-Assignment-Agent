"""Stage 3: raw payloads -> GitHubProfile. Pure; no network.

Everything interpretive lives here so it can be re-run for free. When the
schema or a heuristic changes, re-run `build`, not `collect`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generator.config import COLLECTOR_VERSION, PROFILES_DIR
from generator.github import signals, skill_map
from generator.privacy import scrub
from generator.schemas import (
    ExternalContribution,
    GitHubProfile,
    RepoRecord,
    SkillEvidence,
)
from generator.timeutil import parse_ts


def build_repo(bundle: dict[str, Any], now: datetime | None = None) -> RepoRecord:
    repo = bundle["repo"]
    paths: list[str] = bundle.get("tree_paths", [])
    languages: dict[str, int] = bundle.get("languages") or {}
    contents: dict[str, str] = bundle.get("file_contents") or {}

    readme_key = next((k for k in contents if k.lower().startswith("readme")), None)
    readme = contents.get(readme_key) if readme_key else None

    commit_summary = signals.commit_stats(bundle.get("commits", []))
    # "author" = matched by GitHub login; "sole_author" = owner is the only
    # contributor, so unlinked-email commits were counted too.
    commit_summary["attribution"] = bundle.get("commit_attribution", "author")
    commit_summary["truncated"] = bundle.get("commits_truncated", False)
    commit_summary["messages_sample"] = [scrub(m) for m in commit_summary["messages_sample"]]
    share = bundle.get("contribution_share")

    # Cheap boolean facts the signal functions depend on.
    has_ci = any(p.startswith(".github/workflows/") or p in
                 {".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"} for p in paths)
    has_docker = any(p.lower().endswith("dockerfile") or "docker-compose" in p.lower() for p in paths)
    has_tests = any(
        pattern.search(p) for p in paths
        for pattern, skill, _ in skill_map.FILE_PATTERNS if skill == "unit-testing"
    )

    enriched = dict(repo)
    enriched.update({
        "has_ci": has_ci,
        "has_docker": has_docker,
        "has_tests": has_tests,
        "has_releases": bundle.get("has_releases", False),
        "contributors_count": bundle.get("contributors_count", 1),
        "has_issues_activity": repo.get("open_issues", 0) > 0,
    })

    # -- skills ---------------------------------------------------------
    skill_signals: list[skill_map.SkillSignal] = []
    skill_signals += skill_map.signals_from_languages(languages)
    skill_signals += skill_map.signals_from_tree(paths)
    skill_signals += skill_map.signals_from_topics(repo.get("topics") or [])
    skill_signals += skill_map.signals_from_name(repo.get("name", ""), repo.get("description"))

    manifests: dict[str, list[str]] = {}
    for path, text in contents.items():
        if path.rsplit("/", 1)[-1] not in skill_map.MANIFEST_FILES:
            continue
        deps = skill_map.parse_manifest(path, text)
        if deps:
            manifests[path] = sorted(deps)[:120]
            skill_signals += skill_map.signals_from_dependencies(deps, path)

    # Drop anything that is not a canonical taxonomy id.
    valid = skill_map.skill_ids()
    skill_signals = [s for s in skill_signals if s.skill_id in valid]

    notable = [p for p in paths if p.rsplit("/", 1)[-1] in skill_map.MANIFEST_FILES
               or p.startswith(".github/workflows/")
               or p.lower().endswith("dockerfile")]

    structure = signals.structure_signals(enriched, paths, commit_summary, readme)
    signal_dicts = [s.to_dict() for s in skill_signals]
    relevant, relevance = signals.skill_relevance(
        name=repo.get("name", ""),
        owner=repo.get("owner") or (repo.get("full_name") or "/").split("/")[0],
        is_fork=repo.get("is_fork", False),
        languages=languages,
        structure=structure,
        commit_count=commit_summary.get("count", 0),
        skill_signals=signal_dicts,
        contribution_share=share,
    )

    # The username/username repo is a personal introduction page, not a project:
    # its README is a CV in all but name, so none of it is kept.
    owner = (repo.get("full_name") or "/").split("/")[0]
    is_profile_readme = repo.get("name", "").lower() == owner.lower()
    excerpt = None if is_profile_readme else scrub((readme or "")[:1200] or None)

    return RepoRecord(
        name=repo.get("name", ""),
        full_name=repo.get("full_name", ""),
        html_url=repo.get("html_url", ""),
        description=scrub(repo.get("description")),
        homepage=repo.get("homepage") or None,
        is_fork=repo.get("is_fork", False),
        is_archived=repo.get("is_archived", False),
        is_template=repo.get("is_template", False),
        created_at=repo.get("created_at"),
        pushed_at=repo.get("pushed_at"),
        stargazers=repo.get("stargazers", 0),
        forks=repo.get("forks", 0),
        open_issues=repo.get("open_issues", 0),
        size_kb=repo.get("size_kb", 0),
        default_branch=repo.get("default_branch", "main"),
        license=repo.get("license"),
        topics=repo.get("topics") or [],
        languages=languages,
        primary_language=max(languages.items(), key=lambda kv: kv[1])[0] if languages else None,
        file_count=len(paths),
        top_level_paths=sorted({p.split("/")[0] for p in paths})[:40],
        notable_files=notable[:30],
        manifests=manifests,
        has_readme=bool(readme),
        readme_length=len(readme or ""),
        readme_excerpt=excerpt,
        has_ci=has_ci,
        has_tests=has_tests,
        has_docker=has_docker,
        has_releases=bundle.get("has_releases", False),
        contributors_count=bundle.get("contributors_count", 1),
        contribution_share=share,
        commits=commit_summary,
        structure=structure,
        judgment=signals.judgment_signals(commit_summary, enriched, now),
        skill_signals=signal_dicts,
        skill_relevant=relevant,
        relevance=relevance,
        tree_truncated=bundle.get("tree_truncated", False),
    )


def aggregate_skills(repos: list[RepoRecord]) -> list[SkillEvidence]:
    """Roll per-repo signals up into one evidence record per taxonomy skill."""
    by_skill: dict[str, SkillEvidence] = {}

    for repo in repos:
        first = repo.commits.get("first_at")
        last = repo.commits.get("last_at")
        commit_count = repo.commits.get("count", 0)

        for raw in repo.skill_signals:
            skill_id = raw["skill_id"]
            evidence = by_skill.setdefault(skill_id, SkillEvidence(skill_id=skill_id))

            if repo.full_name not in evidence.repos:
                evidence.repos.append(repo.full_name)
                evidence.commit_count += commit_count
            evidence.signal_count += 1
            if raw["source"] not in evidence.sources:
                evidence.sources.append(raw["source"])
            evidence.max_strength = max(evidence.max_strength, raw["strength"])
            if len(evidence.details) < 12:
                evidence.details.append(f"{repo.name}: {raw['detail']}")

            if raw["source"] == "language":
                language = raw["detail"].split(":")[0]
                evidence.total_bytes += repo.languages.get(language, 0)

            if first and (evidence.first_seen is None or first < evidence.first_seen):
                evidence.first_seen = first
            if last and (evidence.last_seen is None or last > evidence.last_seen):
                evidence.last_seen = last

    return sorted(
        by_skill.values(),
        key=lambda e: (e.max_strength, len(e.repos), e.signal_count),
        reverse=True,
    )


# A profile is only worth keeping if there is enough of a record to verify a
# claim against. Two tiers:
#
#   relaxed - at least 3 repos that are real skill work, and something readable.
#             The floor: enough to check a claim against.
#   strict  - relaxed, plus enough history and breadth to read a pattern from.
#
# Slot assignment (assign.py) fills strata with strict profiles where it can and
# relaxed ones where it must, so a thin-but-real profile still counts.
MIN_SKILL_RELEVANT_REPOS = 3   # repos that are real skill work, see signals.skill_relevance
MIN_READABLE_REPOS = 1
STRICT_MIN_TOTAL_COMMITS = 20
STRICT_MIN_DISTINCT_SKILLS = 3  # at manifest/language strength, not repo-name guesses
MIN_SKILL_STRENGTH = 0.55


def assess_usability(repos: list[RepoRecord],
                     skills: list[SkillEvidence]) -> tuple[str, dict[str, Any]]:
    """Grade a profile: "strict", "relaxed" or "unusable"."""
    relevant = [r for r in repos if r.skill_relevant]
    total_commits = sum(r.commits.get("count", 0) for r in repos)
    strong_skills = [s for s in skills if s.max_strength >= MIN_SKILL_STRENGTH]
    readable = [r for r in repos if r.has_readme or r.manifests]

    relaxed_checks = {
        "skill_relevant_repos": (len(relevant), MIN_SKILL_RELEVANT_REPOS),
        "readable_repos": (len(readable), MIN_READABLE_REPOS),
    }
    strict_checks = {
        "total_commits": (total_commits, STRICT_MIN_TOTAL_COMMITS),
        "distinct_skills": (len(strong_skills), STRICT_MIN_DISTINCT_SKILLS),
    }
    checks = relaxed_checks | strict_checks

    def failures(group: dict[str, tuple[int, int]]) -> list[str]:
        return [name for name, (actual, required) in group.items() if actual < required]

    relaxed_failed = failures(relaxed_checks)
    strict_failed = failures(strict_checks)
    if relaxed_failed:
        tier = "unusable"
    elif strict_failed:
        tier = "relaxed"
    else:
        tier = "strict"

    failed = relaxed_failed + strict_failed
    return tier, {
        "tier": tier,
        "checks": {name: {"actual": a, "required": r,
                          "tier": "relaxed" if name in relaxed_checks else "strict"}
                   for name, (a, r) in checks.items()},
        "failed": failed,
        "reason": "; ".join(
            f"{name}: {checks[name][0]} < {checks[name][1]}" for name in failed
        ) or "meets all thresholds",
    }


def build_profile(bundle: dict[str, Any], applicant_id: str) -> GitHubProfile:
    user = bundle["user"]
    # Time-relative fields are measured from collection, not from whenever build
    # runs, so rebuilding the same raw data always gives byte-identical profiles.
    now = parse_ts(bundle.get("collected_at")) or datetime.now(UTC)
    repos = [build_repo(r, now) for r in bundle.get("repos", [])]

    languages_bytes: dict[str, int] = {}
    for repo in repos:
        for language, count in repo.languages.items():
            languages_bytes[language] = languages_bytes.get(language, 0) + count

    created = parse_ts(user.get("created_at"))
    age_days = (now - created).days if created else 0

    skill_evidence = aggregate_skills(repos)
    tier, usability = assess_usability(repos, skill_evidence)

    notes: list[str] = []
    if tier != "strict":
        notes.append(f"{tier} - {usability['reason']}")
    if len(repos) < 3:
        notes.append("fewer than 3 repos mined - thin evidence base")
    if any(r.tree_truncated for r in repos):
        notes.append("at least one repo tree was truncated by the API")
    if not any(r.commits.get("count") for r in repos):
        notes.append("no commits attributed to this login - check commit email config")

    return GitHubProfile(
        applicant_id=applicant_id,
        login=user["login"],
        html_url=user.get("html_url", ""),
        created_at=user.get("created_at"),
        account_age_days=age_days,
        public_repos=user.get("public_repos", 0),
        followers=user.get("followers", 0),
        following=user.get("following", 0),
        repos=repos,
        external_contributions=[
            ExternalContribution(**e) for e in bundle.get("external_contributions", [])
            if e.get("html_url")
        ],
        languages_bytes=dict(sorted(languages_bytes.items(), key=lambda kv: kv[1], reverse=True)),
        total_commits=sum(r.commits.get("count", 0) for r in repos),
        skill_evidence=skill_evidence,
        tier=tier,
        usability=usability,
        search_stratum=bundle.get("stratum"),
        collected_at=bundle.get("collected_at"),
        collector_version=COLLECTOR_VERSION,
        notes=notes,
    )


def profile_path(applicant_id: str) -> Path:
    return PROFILES_DIR / f"{applicant_id}.json"


def save_profile(profile: GitHubProfile) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = profile_path(profile.applicant_id)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_profile(applicant_id: str) -> GitHubProfile | None:
    path = profile_path(applicant_id)
    if not path.exists():
        return None
    return GitHubProfile.model_validate_json(path.read_text(encoding="utf-8"))


def remove_stale_profiles() -> list[str]:
    """Delete profile files not named by applicant ID - e.g. the old <login>.json.

    Safe: every profile is regenerated from raw/ by `build`.
    """
    from generator.github.ids import ID_PATTERN

    removed = []
    if PROFILES_DIR.exists():
        for path in PROFILES_DIR.glob("*.json"):
            if not ID_PATTERN.match(path.stem):
                path.unlink()
                removed.append(path.name)
    return removed


def load_all_profiles() -> list[GitHubProfile]:
    if not PROFILES_DIR.exists():
        return []
    out = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            out.append(GitHubProfile.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - a malformed profile must not stop the batch
            print(f"  ! skipping {path.name}: {exc}")
    return out
