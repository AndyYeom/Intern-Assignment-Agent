"""Assign each applicant a career direction, spread across the corpus.

data/resumes/career_path.md describes the space: 15 career families and 7
creative types (obvious ... wildcard). Left to itself, every LLM call picks the
obvious path, and separate calls cannot coordinate - five subagents would all
write "Full-Stack Engineer". So the direction is assigned here, deterministically,
over every placed applicant at once, before any prompt is written:

  * a family is only offered when the person's evidence makes it plausible
  * each applicant takes the least-used plausible family, then the least-used
    creative type, so the corpus covers the space evenly
  * the same corpus always yields the same directions, however it is batched

The direction shapes the narrative - objective, major, coursework, activities,
prior domain - never the technical claims, which stay bound to the evidence.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass

from generator.config import DATA
from generator.schemas import GitHubProfile

GUIDE_PATH = DATA / "resumes" / "career_path.md"

INFRA = {"linux", "shell", "docker", "cicd", "aws", "gcp-azure", "kubernetes", "monitoring",
         "go", "c-cpp"}
SECURITY = {"linux", "shell", "auth", "go", "c-cpp", "python", "rest-api", "web-scraping"}
DATA_SKILLS = {"sql", "pandas", "data-viz", "postgresql", "mysql", "etl", "data-modeling",
               "python"}
ML = {"machine-learning", "deep-learning", "nlp", "computer-vision", "llm-apps", "rag", "recsys"}
MOBILE = {"react-native", "flutter", "native-mobile"}
TESTING = {"unit-testing", "integration-testing", "cicd", "code-review"}
DESIGN = {"html-css", "react", "vue", "tailwind", "responsive-design", "accessibility", "ui-ux"}

# (family, the evidence that makes it plausible - None means always plausible)
FAMILIES: list[tuple[str, set[str] | None]] = [
    ("Software Engineering", None),
    ("Systems / Infrastructure / Cloud", INFRA),
    ("Cybersecurity", SECURITY),
    ("Data & Analytics", DATA_SKILLS),
    ("AI / Machine Learning", ML),
    ("Mobile", MOBILE),
    ("QA / Testing / Reliability", TESTING),
    ("UI/UX & Design", DESIGN),
    ("Product Management", None),
    ("Project / Program Management", None),
    ("Engineering Management", None),
    ("Developer Relations / Technical Writing", None),
    ("Consulting / Solutions Engineering", None),
    ("Domain-specialist technology role", None),
    ("Entrepreneurship", None),
]

TYPES = [
    ("A. Obvious", "uses their current skills directly"),
    ("B. Adjacent", "one small skill jump away"),
    ("C. Specialization", "goes deeper into one engineering problem"),
    ("D. Cross-Technical", "moves into another technical discipline"),
    ("E. Leadership / Product", "uses technical knowledge with less hands-on implementation"),
    ("F. Domain Hybrid", "combines an outside profession or field with technology"),
    ("G. Wildcard", "surprising but causally defensible from the evidence"),
]


@dataclass(frozen=True)
class Direction:
    family: str
    creative_type: str
    type_hint: str


def _evidence(profile: GitHubProfile) -> set[str]:
    return {e.skill_id for e in profile.skill_evidence if e.max_strength >= 0.55}


def _rank(applicant_id: str, name: str) -> str:
    """Stable tie-break that is not simply alphabetical."""
    return hashlib.sha256(f"{applicant_id}:{name}".encode()).hexdigest()


def assign_directions(profiles: list[GitHubProfile]) -> dict[str, Direction]:
    family_use: Counter[str] = Counter()
    type_use: Counter[str] = Counter()
    directions: dict[str, Direction] = {}

    for profile in sorted(profiles, key=lambda p: p.applicant_id):
        skills = _evidence(profile)
        plausible = [name for name, needs in FAMILIES if needs is None or skills & needs]
        family = min(plausible, key=lambda f: (family_use[f], _rank(profile.applicant_id, f)))
        family_use[family] += 1

        creative, hint = min(TYPES, key=lambda t: (type_use[t[0]],
                                                    _rank(profile.applicant_id, t[0])))
        type_use[creative] += 1
        directions[profile.applicant_id] = Direction(family, creative, hint)
    return directions


def corpus_directions() -> dict[str, Direction]:
    """Directions for every placed applicant, so any subset is consistent with the whole."""
    from generator.github import assign, normalize

    placed = assign.current().placed_ids
    return assign_directions([p for p in normalize.load_all_profiles()
                              if p.applicant_id in placed])


def guide() -> str:
    return GUIDE_PATH.read_text(encoding="utf-8").strip() if GUIDE_PATH.exists() else ""
