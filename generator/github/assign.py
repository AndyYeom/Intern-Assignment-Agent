"""Place collected profiles into stratum slots.

A person is not tied to the search that found them. GitHub's `language:Go`
matches anyone with any Go repo - often a fork - so the search stratum says how
someone was *found*, not what they *build*. Eligibility is instead read from
their own skill-relevant repos, and one person can be a candidate for several
strata: C#, Python and TypeScript repos make them eligible for all three.

Each person gets a probability for every stratum. Every skill-relevant repo
spreads one unit across the strata it touches, weighted by language bytes, and
skill evidence counts too (a react-native dependency, a pubspec.yaml, a go.mod).
p(stratum) is the person's share across all their relevant repos. A backend
written in Go but outweighed by TypeScript still gives real Go probability.

Each (person, stratum) pair is graded:

  strict   - strict profile, and 2+ relevant repos mainly in the stratum
  relaxed  - 1+ relevant repo mainly in the stratum
  partial  - any real evidence at all (p > 0)

Slots are filled by an optimal assignment (the same solver the scoring agent
uses), with priorities in this order:

  1. fill as many slots as possible
  2. never drop someone already committed to the resume corpus
  3. strict before relaxed before partial
  4. keep committed people in their previous stratum
  5. least surprise: minimise -log2 p(stratum), so people go where their
     evidence is most concentrated

A stratum is only a balancing label and never appears on a resume, so moving a
person between strata is harmless. Dropping them from the corpus is not.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from generator import config
from generator.schemas import GitHubProfile, RepoRecord

# Which GitHub languages count towards each stratum. Keys must match sampler.STRATA.
STRATUM_LANGUAGES: dict[str, frozenset[str]] = {
    "python-backend": frozenset({"python"}),
    "python-data-ml": frozenset({"jupyter notebook"}),
    "javascript-frontend": frozenset({"javascript", "html", "css", "scss", "vue", "svelte"}),
    "typescript-fullstack": frozenset({"typescript"}),
    "java-backend": frozenset({"java"}),
    "go-systems": frozenset({"go"}),
    "cpp-systems": frozenset({"c", "c++"}),
    "mobile": frozenset({"dart", "swift", "objective-c"}),
    "csharp": frozenset({"c#"}),
    "android-kotlin": frozenset({"kotlin"}),
}

# Skills that count as evidence for a stratum even when its language is a minor
# share of the repo: a React Native app is mostly JavaScript, a Flutter app's
# native shells are Kotlin and Swift.
STRATUM_SKILLS: dict[str, frozenset[str]] = {
    "python-backend": frozenset({"django", "flask-fastapi"}),
    "python-data-ml": frozenset(),          # filled from DATA_ML_SKILLS below
    "javascript-frontend": frozenset({"react", "vue", "html-css", "state-management"}),
    "typescript-fullstack": frozenset({"nextjs"}),
    "java-backend": frozenset({"spring"}),
    "go-systems": frozenset({"go"}),
    "cpp-systems": frozenset({"c-cpp"}),
    "mobile": frozenset({"flutter", "react-native", "native-mobile"}),
    "csharp": frozenset({"csharp"}),
    "android-kotlin": frozenset(),
}

# Hybrid mobile frameworks have no taxonomy skill of their own, but a Capacitor or
# Ionic app is still mobile work.
STRATUM_DEPENDENCIES: dict[str, frozenset[str]] = {
    "mobile": frozenset({"react-native", "expo", "@capacitor/core", "@ionic/angular",
                         "@ionic/react", "@ionic/vue", "cordova", "nativescript"}),
}

# Python repos carrying these skills count as data/ML work rather than backend.
DATA_ML_SKILLS = frozenset({
    "pandas", "machine-learning", "deep-learning", "nlp", "computer-vision",
    "data-viz", "recsys", "rag", "llm-apps",
})

# A stratum is a repo's *main* work if its language is the primary one or this share.
MIN_LANGUAGE_SHARE = 0.25
# Below this many bytes a language is a stray file, not evidence of anything.
MIN_TOUCH_BYTES = 1_000
# The weight skill or dependency evidence gives a stratum within one repo.
SKILL_TOUCH_WEIGHT = 0.3

STRICT_MIN_SUPPORT = 2
RELAXED_MIN_SUPPORT = 1
TIER_RANK = {"strict": 0, "relaxed": 1, "partial": 2}

# Cost scale. Each priority level must outweigh the largest possible total of all
# lower levels across every slot, so one minimisation yields the priority order.
MAX_SLOTS = 200
MIN_P = 0.01
MAX_SURPRISAL = -math.log2(MIN_P)                                  # ~6.64 per placement
COST_PREVIOUS_STRATUM_BONUS = -(MAX_SURPRISAL * MAX_SLOTS + 1)     # beats all surprisal
COST_TIER_STEP = abs(COST_PREVIOUS_STRATUM_BONUS) * MAX_SLOTS + 1  # beats all stay-put bonuses
COST_HAS_RESUME_BONUS = -(COST_TIER_STEP * 2 * MAX_SLOTS + 1)      # beats all tier costs
COST_INELIGIBLE = abs(COST_HAS_RESUME_BONUS) * MAX_SLOTS + 1       # beats everything


@dataclass
class Eligibility:
    stratum: str
    tier: str            # "strict" | "relaxed" | "partial"
    support: int         # relevant repos whose main work is in this stratum
    share: float         # p(stratum): this person's probability mass here
    repos: list[str] = field(default_factory=list)   # every relevant repo touching it


@dataclass
class Placement:
    applicant_id: str
    login: str
    stratum: str
    tier: str
    support: int
    share: float
    pinned: bool = False       # batched or rendered: committed to the resume corpus


@dataclass
class Assignment:
    quota: int
    strata: list[str]
    placements: list[Placement]
    eligibility: dict[str, list[Eligibility]]   # applicant_id -> eligible strata

    def filled(self, stratum: str, tier: str | None = None) -> int:
        return sum(1 for p in self.placements
                   if p.stratum == stratum and (tier is None or p.tier == tier))

    def need(self, stratum: str) -> int:
        return max(0, self.quota - self.filled(stratum))

    def eligible_count(self, stratum: str) -> int:
        return sum(1 for options in self.eligibility.values()
                   if any(e.stratum == stratum for e in options))

    @property
    def placed_ids(self) -> set[str]:
        return {p.applicant_id for p in self.placements}

    def to_json(self) -> dict[str, Any]:
        # No timestamp: rebuilding unchanged data must produce no git diff.
        return {
            "quota": self.quota,
            "strata": {
                s: {"filled": self.filled(s), "strict": self.filled(s, "strict"),
                    "relaxed": self.filled(s, "relaxed"), "partial": self.filled(s, "partial"),
                    "need": self.need(s),
                    "eligible": self.eligible_count(s)}
                for s in self.strata
            },
            "placements": [asdict(p) for p in sorted(
                self.placements, key=lambda p: (self.strata.index(p.stratum), p.applicant_id))],
            "spare": sorted(set(self.eligibility) - self.placed_ids),
        }


def _strong_skills(repo: RepoRecord) -> set[str]:
    return {s["skill_id"] for s in repo.skill_signals
            if s.get("strength", 0) >= 0.55 and s.get("source") in {"language", "manifest", "file"}}


def _main_strata(repo: RepoRecord) -> set[str]:
    """Strata this repo is mainly about: its primary language, or 25%+ of its bytes."""
    total = sum(repo.languages.values()) or 1
    languages = {name.lower() for name, count in repo.languages.items()
                 if count / total >= MIN_LANGUAGE_SHARE}
    if repo.primary_language:
        languages.add(repo.primary_language.lower())
    strata = {s for s, langs in STRATUM_LANGUAGES.items() if languages & langs}
    if "python" in languages and _strong_skills(repo) & DATA_ML_SKILLS:
        strata.add("python-data-ml")
        strata.discard("python-backend")
    return strata


def repo_distribution(repo: RepoRecord) -> dict[str, float]:
    """Spread one unit of this repo across every stratum it shows evidence for."""
    total = sum(repo.languages.values()) or 1
    weights: dict[str, float] = {}
    for stratum, langs in STRATUM_LANGUAGES.items():
        stratum_bytes = sum(count for name, count in repo.languages.items()
                            if name.lower() in langs)
        if stratum_bytes >= MIN_TOUCH_BYTES:
            weights[stratum] = stratum_bytes / total

    strong = _strong_skills(repo)
    deps = {d for values in repo.manifests.values() for d in values}
    for stratum in STRATUM_LANGUAGES:
        skills = STRATUM_SKILLS.get(stratum, frozenset())
        if stratum == "python-data-ml":
            skills = DATA_ML_SKILLS
        if strong & skills or deps & STRATUM_DEPENDENCIES.get(stratum, frozenset()):
            weights[stratum] = max(weights.get(stratum, 0.0), SKILL_TOUCH_WEIGHT)

    # Python doing data/ML work is data/ML, not backend.
    if "python-backend" in weights and strong & DATA_ML_SKILLS:
        moved = weights.pop("python-backend")
        weights["python-data-ml"] = max(weights.get("python-data-ml", 0.0), moved)

    mass = sum(weights.values())
    return {s: w / mass for s, w in weights.items()} if mass else {}


def eligibility(profile: GitHubProfile) -> list[Eligibility]:
    """Every stratum this person could fill, with its tier and probability."""
    if profile.tier == "unusable":
        return []
    relevant = [r for r in profile.repos if r.skill_relevant]
    if not relevant:
        return []

    probability: dict[str, float] = {}
    touching: dict[str, list[str]] = {}
    main: dict[str, int] = {}
    for repo in relevant:
        for stratum, weight in repo_distribution(repo).items():
            probability[stratum] = probability.get(stratum, 0.0) + weight / len(relevant)
            touching.setdefault(stratum, []).append(repo.name)
        for stratum in _main_strata(repo):
            main[stratum] = main.get(stratum, 0) + 1
            probability.setdefault(stratum, 0.0)
            touching.setdefault(stratum, [])
            if repo.name not in touching[stratum]:
                touching[stratum].append(repo.name)

    out = []
    for stratum, p in probability.items():
        support = main.get(stratum, 0)
        if profile.tier == "strict" and support >= STRICT_MIN_SUPPORT:
            tier = "strict"
        elif support >= RELAXED_MIN_SUPPORT:
            tier = "relaxed"
        else:
            tier = "partial"
        out.append(Eligibility(stratum, tier, support, round(p, 4), touching[stratum]))
    return sorted(out, key=lambda e: (TIER_RANK[e.tier], -e.share, e.stratum))


def placement_cost(option: Eligibility, *, committed: bool, previous: str | None) -> float:
    """Lower is better. See the cost scale above for why the magnitudes nest."""
    value = COST_TIER_STEP * TIER_RANK[option.tier] - math.log2(max(option.share, MIN_P))
    if committed:
        value += COST_HAS_RESUME_BONUS
        if previous == option.stratum:
            value += COST_PREVIOUS_STRATUM_BONUS
    return value


def assign(
    profiles: list[GitHubProfile],
    strata: list[str],
    quota: int,
    pinned: dict[str, str | None] | None = None,
) -> Assignment:
    """Optimal placement of profiles into `quota` slots per stratum.

    `pinned` maps applicant_id -> previous stratum (or None) for people who
    already have a rendered resume. They are kept in the corpus while still
    eligible anywhere, preferably in the stratum they held before.
    """
    pinned = pinned or {}
    people = sorted((p for p in profiles if p.usable), key=lambda p: p.applicant_id)
    options = {p.applicant_id: eligibility(p) for p in people}
    people = [p for p in people if options[p.applicant_id]]

    slots = [s for s in strata for _ in range(quota)]
    if len(slots) > MAX_SLOTS:
        raise ValueError(f"{len(slots)} slots exceeds MAX_SLOTS={MAX_SLOTS}; raise it")
    if not people or not slots:
        return Assignment(quota, strata, [], {k: v for k, v in options.items() if v})

    cost = np.full((len(people), len(slots)), COST_INELIGIBLE)
    for row, person in enumerate(people):
        by_stratum = {e.stratum: e for e in options[person.applicant_id]}
        for col, stratum in enumerate(slots):
            option = by_stratum.get(stratum)
            if option is None:
                continue
            cost[row, col] = placement_cost(
                option, committed=person.applicant_id in pinned,
                previous=pinned.get(person.applicant_id))

    rows, cols = linear_sum_assignment(cost)
    placements = []
    for row, col in zip(rows, cols, strict=True):
        if cost[row, col] >= COST_INELIGIBLE:
            continue
        person = people[row]
        option = next(e for e in options[person.applicant_id] if e.stratum == slots[col])
        placements.append(Placement(
            applicant_id=person.applicant_id,
            login=person.login,
            stratum=option.stratum,
            tier=option.tier,
            support=option.support,
            share=option.share,
            pinned=person.applicant_id in pinned,
        ))

    return Assignment(quota, strata, placements, {k: v for k, v in options.items() if v})


# -- disk -------------------------------------------------------------------

CORPUS_PATH = config.GITHUB_DATA / "corpus.json"


def pins_from_disk() -> dict[str, str | None]:
    """People already committed to the resume corpus, mapped to their previous stratum.

    Committed means batched by `re plan` (someone may be writing their resume
    right now) or rendered into applicants.csv. Pinning only at render time would
    let a rebuild drop a person whose resume is half-written.
    """
    import csv

    committed: set[str] = set()
    manifest_path = config.DATA / "applicants.csv"
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            committed |= {row["applicant_id"] for row in csv.DictReader(handle)
                          if row.get("applicant_id")}

    roster_path = config.DATA / "resumes" / "roster.json"
    if roster_path.exists():
        roster = json.loads(roster_path.read_text(encoding="utf-8"))
        for batch in roster.get("batches", []):
            committed |= set(batch.get("applicant_ids", []))

    previous: dict[str, str] = {}
    if CORPUS_PATH.exists():
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        previous = {p["applicant_id"]: p["stratum"] for p in corpus.get("placements", [])}
    return {applicant: previous.get(applicant) for applicant in committed}


def current(target: int = config.TARGET_PROFILE_COUNT) -> Assignment:
    """Assign from the profiles on disk. Pure computation; writes nothing."""
    from generator.github import normalize, sampler

    strata = list(sampler.STRATA)
    return assign(normalize.load_all_profiles(), strata,
                  sampler.stratum_quota(target, len(strata)), pins_from_disk())


def save(assignment: Assignment) -> None:
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(json.dumps(assignment.to_json(), indent=2), encoding="utf-8")
