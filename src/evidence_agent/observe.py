"""What level of a skill the GitHub record supports.

Applies the boundary tests in data/proficiency_levels.md to the signals the
collector already mined, one repository at a time:

  Entry (1)         the repo exists, but looks follow-along: tutorial name,
                    template, notebook or single file, one day of commits.
  Intermediate (2)  they made the structural decisions: several commits over
                    time, plus signs of real work (tests, CI, deployment,
                    documentation, other users).
  Advanced (3)      judgment under difficulty: others depend on it, or
                    sustained maintenance with fix/perf/refactor commits.

A skill's observed level is its best repository. Ambiguity resolves downward.
Absence is never evidence against a claim; it is `None` (not observed).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from generator.schemas import GitHubProfile, RepoRecord

from .evidence_models import Strength

# Sources that show the skill was actually used. Topics and repo names are
# self-declared and never enough on their own.
HARD_SOURCES = {"language", "manifest", "file"}
MIN_SIGNAL_STRENGTH = 0.5
MIN_COMMITS_INTERMEDIATE = 5
FOLLOW_ALONG_FLAGS = ("tutorial_name_hit", "follow_along_phrase", "is_template",
                      "notebook_only", "single_file_project", "single_commit",
                      "all_commits_one_day")
INDEPENDENT_WORK_FLAGS = ("has_ci", "has_tests", "has_docker", "deployed",
                          "multi_month_span", "many_active_days", "used_by_others",
                          "documented")


@dataclass
class Observation:
    skill_id: str
    level: int | None = None
    strength: Strength = "none"
    repos: list[tuple[RepoRecord, int, list[str]]] = field(default_factory=list)
    weak_only: bool = False


def _own_work(repo: RepoRecord) -> bool:
    rules = repo.relevance.get("rules", {})
    return not repo.is_fork and rules.get("own_commits", True) and rules.get("own_share", True)


def repo_level(repo: RepoRecord) -> tuple[int, list[str]]:
    entry = repo.structure.get("entry_flags", {})
    inter = repo.structure.get("intermediate_flags", {})
    commits = int(repo.commits.get("count", 0) or 0)

    follow = [f for f in FOLLOW_ALONG_FLAGS if entry.get(f)]
    independent = [f for f in INDEPENDENT_WORK_FLAGS if inter.get(f)]
    if follow:
        return 1, [f"entry: {', '.join(follow)}"]
    if commits < MIN_COMMITS_INTERMEDIATE or len(independent) < 2:
        signals = ", ".join(independent) or "none"
        return 1, [f"entry: {commits} commits, independent-work signals: {signals}"]

    reasons = [f"intermediate: {commits} commits; {', '.join(independent)}"]
    judgment = repo.judgment
    kinds = judgment.get("commit_message_kinds", {})
    judged = sum(int(kinds.get(k, 0) or 0) for k in ("fix", "perf", "refactor"))
    if judgment.get("others_depend"):
        return 3, [*reasons, "advanced: others depend on it"]
    if judged >= 3 and judgment.get("sustained_maintenance"):
        return 3, [*reasons, f"advanced: sustained maintenance, {judged} fix/perf/refactor commits"]
    return 2, reasons


def observe(profile: GitHubProfile, skill_id: str) -> Observation:
    obs = Observation(skill_id)
    weak_seen = False
    for repo in profile.repos:
        signals = [s for s in repo.skill_signals if s.get("skill_id") == skill_id]
        if not signals:
            continue
        hard = [s for s in signals
                if s.get("source") in HARD_SOURCES and s.get("strength", 0) >= MIN_SIGNAL_STRENGTH]
        if not hard or not _own_work(repo):
            weak_seen = True
            continue
        level, reasons = repo_level(repo)
        obs.repos.append((repo, level, [*reasons, *(s["detail"] for s in hard[:2])]))

    if not obs.repos:
        obs.weak_only = weak_seen
        obs.strength = "weak" if weak_seen else "none"
        return obs

    obs.repos.sort(key=lambda r: (-r[1], r[0].full_name))
    obs.level = obs.repos[0][1]
    solid = sum(1 for _, level, _ in obs.repos if level >= 2)
    if solid >= 2 or obs.level == 3:
        obs.strength = "strong"
    elif solid == 1 or len(obs.repos) >= 2:
        obs.strength = "moderate"
    else:
        obs.strength = "weak"
    return obs


def observed_skills(profile: GitHubProfile) -> list[str]:
    ids = {s.get("skill_id") for r in profile.repos for s in r.skill_signals}
    return sorted(i for i in ids if i)
