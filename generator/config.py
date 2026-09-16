"""Paths, tunables and environment for the data generator."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
TAXONOMY_PATH = DATA / "taxonomy.json"

GITHUB_DATA = DATA / "githubs"
CANDIDATES_PATH = GITHUB_DATA / "candidates.json"
RAW_DIR = GITHUB_DATA / "raw"
PROFILES_DIR = GITHUB_DATA / "profiles"

CACHE_DIR = ROOT / ".cache" / "github"

COLLECTOR_VERSION = "0.1.0"

API_ROOT = "https://api.github.com"
USER_AGENT = "intern-assignment-agent-evidence-collector/0.1"

# How many repos we mine per user. A real resume lists a handful of selected
# projects, not everything on the account, so the corpus mirrors that. Repos are
# ranked by substance first, so the cap drops throwaways, not the interesting work.
MAX_REPOS_PER_USER = 5

# Commits are paged at 100; one page is plenty to characterise a student repo.
MAX_COMMIT_PAGES = 2

TARGET_PROFILE_COUNT = 40


def _load_dotenv() -> None:
    """Minimal .env reader so no extra dependency is needed."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def github_token() -> str | None:
    _load_dotenv()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return token.strip() or None if token else None
