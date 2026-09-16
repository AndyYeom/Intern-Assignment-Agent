"""Derive the boundary evidence the proficiency scale actually asks for.

data/proficiency_levels.md poses two decisive questions. Both are detectable:

  Entry vs Intermediate - "did the applicant make the structural decisions,
                           or follow someone else's?"
  Intermediate vs Advanced - "is there evidence of judgment under difficulty?"

Everything here is a *positive* observation. Nothing subtracts. Absence of a
signal means `not_observed`, never a level below Entry - which is the rule the
Evidence agent is bound by.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from generator.timeutil import parse_ts

# Repo names that almost always mean "I followed a guide".
TUTORIAL_NAME_PATTERNS = [
    re.compile(r"(^|[-_])clone([-_]|$)", re.IGNORECASE),
    re.compile(r"tutorial|bootcamp|course(work)?|lesson|exercise|practice|workshop", re.IGNORECASE),
    re.compile(r"(^|[-_])(todo|to-?do)([-_]?(app|list))?([-_]|$)", re.IGNORECASE),
    re.compile(r"^(hello[-_]?world|my[-_]?first|learn(ing)?[-_])", re.IGNORECASE),
    re.compile(r"\d{2,3}[-_]days?([-_]of)?[-_]", re.IGNORECASE),
    re.compile(r"(^|[-_])(assignment|homework|lab\d*|week\d+|day\d+)([-_]|$)", re.IGNORECASE),
    re.compile(r"(freecodecamp|the[-_]?odin|cs50|leetcode|hackerrank|codewars|advent[-_]?of[-_]?code)", re.IGNORECASE),
    re.compile(r"(^|[-_])(demo|sample|test|playground|sandbox|scratch)([-_]|$)", re.IGNORECASE),
    re.compile(r"(portfolio|starter|boilerplate|template)", re.IGNORECASE),
]

FOLLOW_ALONG_PHRASES = [
    "following along", "follow along", "this tutorial", "built while following",
    "from the course", "part of the course", "udemy", "coursera", "freecodecamp",
    "this is my first", "learning project", "practice project", "based on the tutorial",
    "created with create-react-app", "bootstrapped with",
    "following a", "following the", "youtube tutorial", "video tutorial",
    "walkthrough", "step by step guide", "as taught", "class project",
    "for my course", "university assignment", "school project",
]

# Commit messages that suggest debugging / trade-offs rather than "add file".
JUDGMENT_COMMIT_PATTERNS = {
    "fix": re.compile(r"\b(fix(e[sd])?|bug(fix)?|resolve[sd]?|patch|hotfix|correct)\b", re.IGNORECASE),
    "perf": re.compile(r"\b(perf|performance|optimi[sz]e[sd]?|speed ?up|faster|cache|memo|reduce)\b", re.IGNORECASE),
    "refactor": re.compile(r"\b(refactor(ed|ing)?|restructure|clean ?up|simplif(y|ied)|rewrite|extract)\b", re.IGNORECASE),
    "test": re.compile(r"\b(test(s|ing)?|coverage|regression)\b", re.IGNORECASE),
    "revert": re.compile(r"\b(revert(ed)?|rollback)\b", re.IGNORECASE),
}

LOW_EFFORT_COMMIT = re.compile(
    r"^(update|updated|u|commit|changes?|edit|wip|asdf*|\.+|final|new file|"
    r"initial commit|first commit|add files via upload|create [\w.]+|update [\w.]+)$",
    re.IGNORECASE,
)

NOTEBOOK_EXT = ".ipynb"
CODE_EXTS = {
    ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".java", ".go", ".c", ".cc", ".cpp",
    ".cxx", ".h", ".hpp", ".cs", ".rb", ".php", ".rs", ".kt", ".kts", ".swift", ".m",
    ".mm", ".dart", ".vue", ".svelte", ".sh", ".ps1", ".sql", ".r", ".scala", ".lua",
    ".gd", ".html", ".css", ".scss", ".sass", ".less",
}




def commit_stats(commits: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise a user's commits in one repo."""
    dates: list[datetime] = []
    messages: list[str] = []
    for commit in commits:
        node = (commit.get("commit") or {})
        stamp = parse_ts((node.get("author") or {}).get("date"))
        if stamp:
            dates.append(stamp)
        message = (node.get("message") or "").strip().splitlines()
        if message:
            messages.append(message[0][:200])

    if not dates:
        return {
            "count": len(commits), "first_at": None, "last_at": None,
            "active_days": 0, "span_days": 0, "max_per_day": 0,
            "low_effort_message_ratio": 0.0, "messages_sample": messages[:20],
        }

    dates.sort()
    day_counts: dict[str, int] = {}
    for stamp in dates:
        key = stamp.date().isoformat()
        day_counts[key] = day_counts.get(key, 0) + 1

    low_effort = sum(1 for m in messages if LOW_EFFORT_COMMIT.match(m.strip()))
    return {
        "count": len(commits),
        "first_at": dates[0].isoformat(),
        "last_at": dates[-1].isoformat(),
        "active_days": len(day_counts),
        "span_days": (dates[-1] - dates[0]).days,
        "max_per_day": max(day_counts.values()),
        "low_effort_message_ratio": round(low_effort / len(messages), 3) if messages else 0.0,
        "messages_sample": messages[:20],
    }


def judgment_signals(commit_summary: dict[str, Any], repo: dict[str, Any],
                     now: datetime | None = None) -> dict[str, Any]:
    """Intermediate vs Advanced evidence: judgment under difficulty."""
    messages = commit_summary.get("messages_sample", [])
    counts = {
        label: sum(1 for m in messages if pattern.search(m))
        for label, pattern in JUDGMENT_COMMIT_PATTERNS.items()
    }

    last = parse_ts(commit_summary.get("last_at"))
    recently_active = bool(
        last and ((now or datetime.now(UTC)) - last).days < 365
    )

    return {
        "commit_message_kinds": counts,
        "sustained_maintenance": commit_summary.get("span_days", 0) >= 90
        and commit_summary.get("active_days", 0) >= 10,
        "recently_active": recently_active,
        "has_releases": repo.get("has_releases", False),
        "others_depend": (repo.get("stargazers", 0) >= 3 or repo.get("forks", 0) >= 2),
        "multi_contributor": repo.get("contributors_count", 1) > 1,
        "handles_issues": repo.get("has_issues_activity", False),
    }


def structure_signals(
    repo: dict[str, Any],
    paths: Iterable[str],
    commit_summary: dict[str, Any],
    readme: str | None,
) -> dict[str, Any]:
    """Entry vs Intermediate evidence: who made the structural decisions."""
    paths = list(paths)
    name = repo.get("name", "")
    description = repo.get("description") or ""

    notebooks = [p for p in paths if p.lower().endswith(NOTEBOOK_EXT)]
    code_files = [p for p in paths if any(p.lower().endswith(e) for e in CODE_EXTS)]

    # The give-away phrase lands in the description as often as in the README.
    prose = f"{readme or ''}\n{description}".lower()
    follow_along = [phrase for phrase in FOLLOW_ALONG_PHRASES if phrase in prose]

    tutorial_hits = [
        pattern.pattern for pattern in TUTORIAL_NAME_PATTERNS
        if pattern.search(f"{name} {description}")
    ]

    active_days = commit_summary.get("active_days", 0)
    span_days = commit_summary.get("span_days", 0)

    entry_flags = {
        "is_fork": bool(repo.get("is_fork")),
        "single_commit": commit_summary.get("count", 0) <= 1,
        "all_commits_one_day": active_days <= 1 and commit_summary.get("count", 0) > 0,
        "burst_only": span_days <= 3 and commit_summary.get("count", 0) > 1,
        "notebook_only": bool(notebooks) and not code_files,
        "single_file_project": len(code_files) <= 1 and not notebooks,
        "tutorial_name_hit": bool(tutorial_hits),
        "follow_along_phrase": bool(follow_along),
        "no_readme": not readme,
        "is_template": bool(repo.get("is_template")),
        "mostly_low_effort_commits": commit_summary.get("low_effort_message_ratio", 0.0) >= 0.5
        and commit_summary.get("count", 0) >= 5,
    }

    intermediate_flags = {
        "has_ci": repo.get("has_ci", False),
        "has_tests": repo.get("has_tests", False),
        "has_docker": repo.get("has_docker", False),
        "deployed": bool(repo.get("homepage")),
        "multi_month_span": span_days >= 60 and active_days >= 5,
        "many_active_days": active_days >= 8,
        "used_by_others": repo.get("stargazers", 0) >= 3 or repo.get("forks", 0) >= 2,
        "has_license": bool(repo.get("license")),
        "substantial_tree": len(code_files) >= 8,
        "documented": bool(readme) and len(readme or "") > 800,
    }

    return {
        "entry_flags": entry_flags,
        "intermediate_flags": intermediate_flags,
        "entry_flag_count": sum(entry_flags.values()),
        "intermediate_flag_count": sum(intermediate_flags.values()),
        "tutorial_name_matches": tutorial_hits,
        "follow_along_phrases": follow_along,
        "notebook_count": len(notebooks),
        "code_file_count": len(code_files),
    }


def repo_substance_score(repo: dict[str, Any]) -> float:
    """Rank repos so the per-user cap drops throwaways, not the interesting work.

    Ranking only - this never feeds a proficiency level.
    """
    if repo.get("is_fork"):
        return -1.0
    # Below every real candidate, but above forks: still mined if nothing better exists.
    if is_non_project_name(repo.get("name") or "", repo.get("owner")):
        return -0.5
    if not repo.get("language"):
        return -0.25  # no detectable code at all - usually text or empty
    score = 0.0
    score += min(repo.get("size_kb", 0) / 500.0, 6.0)
    score += min(repo.get("stargazers", 0), 10) * 1.5
    score += min(repo.get("forks", 0), 5) * 1.0
    score += 3.0 if repo.get("description") else 0.0
    score += 2.0 * len(repo.get("topics") or [])
    score += 4.0 if repo.get("homepage") else 0.0
    score += 2.0 if repo.get("license") else 0.0
    pushed_at = parse_ts(repo.get("pushed_at"))
    if pushed_at is not None:
        age_days = (datetime.now(UTC) - pushed_at).days
        score += max(0.0, 4.0 - age_days / 365.0)
    return score


# -- skill relevance ------------------------------------------------------
#
# A repo can have commits and a README and still be no evidence of any skill:
# lecture notes, dotfiles, an awesome-list, a CV, the profile README. These
# rules decide whether a repo is real skill work. A profile needs several such
# repos before it is worth verifying claims against.

# Anchored at the end of the name on purpose. Non-project repos end in the
# keyword ("lecture-notes", "nvim-config"); projects merely start with one
# ("config-parser-rs", "note-taking-app"), and those must not be thrown out.
NON_PROJECT_NAME_PATTERNS = [
    re.compile(r"(^|[-_.])dotfiles?$", re.IGNORECASE),
    re.compile(r"(^|[-_])(notes?|til|journal|diary|blog-?posts?)$", re.IGNORECASE),
    re.compile(r"^awesome[-_]", re.IGNORECASE),
    re.compile(r"^(my[-_])?(resume|cv|curriculum-?vitae)$", re.IGNORECASE),
    re.compile(r"(^|[-_])(cheat-?sheets?|interview-?(prep|questions)|roadmaps?|books|"
               r"reading-?list)$", re.IGNORECASE),
    re.compile(r"(^|[-_])(configs?|settings|setup|env)$", re.IGNORECASE),
    re.compile(r"^\.github$", re.IGNORECASE),
]

# Relevance asks "is this skill work?", not "how advanced is it?". A single
# 40 KB script or one analysis notebook is skill work - Entry level, which the
# structure flags record - and Entry profiles are exactly where planted
# exaggerations get caught. So the floors here only exclude text and empty repos.
MIN_RELEVANT_CODE_FILES = 1
MIN_RELEVANT_NOTEBOOKS = 1
MIN_RELEVANT_CODE_BYTES = 2_000
MIN_RELEVANT_COMMITS = 1
# In a shared repo, the person must have written at least this share of commits.
# Four equal teammates (25% each) pass; being one of six does not.
MIN_RELEVANT_CONTRIBUTION_SHARE = 0.2
MIN_RELEVANT_SIGNAL_STRENGTH = 0.55
STRONG_SOURCES = {"language", "manifest", "file"}


def is_non_project_name(name: str, owner: str | None = None) -> bool:
    """True for repos whose name says they are not a project."""
    if owner and name.lower() == owner.lower():
        return True  # the username/username profile README
    return any(pattern.search(name) for pattern in NON_PROJECT_NAME_PATTERNS)


def skill_relevance(
    *,
    name: str,
    owner: str | None,
    is_fork: bool,
    languages: dict[str, int],
    structure: dict[str, Any],
    commit_count: int,
    skill_signals: list[dict[str, Any]],
    contribution_share: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Decide whether one repo is real skill work rather than text or config.

    Every rule must pass. Returns the verdict plus each rule's outcome, so a
    rejection can be read and the thresholds tuned.
    """
    from generator.github.skill_map import LANGUAGE_TO_SKILL

    # Only bytes in a language that maps to a taxonomy skill. Markdown and TeX
    # are not in the map, so a notes repo scores zero here however large it is.
    code_bytes = sum(
        count for language, count in languages.items()
        if language.lower() in LANGUAGE_TO_SKILL
    )
    code_files = structure.get("code_file_count", 0)
    notebooks = structure.get("notebook_count", 0)
    strong = [
        s for s in skill_signals
        if s.get("source") in STRONG_SOURCES
        and s.get("strength", 0) >= MIN_RELEVANT_SIGNAL_STRENGTH
    ]

    rules = {
        "not_fork": not is_fork,
        "project_name": not is_non_project_name(name, owner),
        "has_code_files": code_files >= MIN_RELEVANT_CODE_FILES
        or notebooks >= MIN_RELEVANT_NOTEBOOKS,
        "code_bytes": code_bytes >= MIN_RELEVANT_CODE_BYTES,
        "strong_skill_signal": bool(strong),
        "own_commits": commit_count >= MIN_RELEVANT_COMMITS,
        "own_share": contribution_share is None
        or contribution_share >= MIN_RELEVANT_CONTRIBUTION_SHARE,
    }
    failed = [rule for rule, ok in rules.items() if not ok]
    return not failed, {
        "rules": rules,
        "failed": failed,
        "code_bytes": code_bytes,
        "strong_skills": sorted({s["skill_id"] for s in strong}),
    }
