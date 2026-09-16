"""Shared schemas for the data C produces.

`GitHubProfile` is the contract for two consumers:
  * the resume generator - drafts a synthetic resume from it
  * the evidence agent - verifies the resume's claims against it

Kept deliberately flat and JSON-first so it can be read without importing this
package.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillEvidence(BaseModel):
    """All observations supporting one taxonomy skill, across all repos."""

    skill_id: str
    repos: list[str] = Field(default_factory=list)
    signal_count: int = 0
    sources: list[str] = Field(default_factory=list)
    max_strength: float = 0.0
    total_bytes: int = 0
    commit_count: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    details: list[str] = Field(default_factory=list)


class RepoRecord(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    homepage: str | None = None
    is_fork: bool = False
    is_archived: bool = False
    is_template: bool = False
    created_at: str | None = None
    pushed_at: str | None = None
    stargazers: int = 0
    forks: int = 0
    open_issues: int = 0
    size_kb: int = 0
    default_branch: str = "main"
    license: str | None = None
    topics: list[str] = Field(default_factory=list)

    languages: dict[str, int] = Field(default_factory=dict)
    primary_language: str | None = None

    file_count: int = 0
    top_level_paths: list[str] = Field(default_factory=list)
    notable_files: list[str] = Field(default_factory=list)
    manifests: dict[str, list[str]] = Field(default_factory=dict)

    has_readme: bool = False
    readme_length: int = 0
    readme_excerpt: str | None = None

    has_ci: bool = False
    has_tests: bool = False
    has_docker: bool = False
    has_releases: bool = False
    contributors_count: int = 1
    # This person's share of all commits, counting unlinked identities. None when
    # GitHub could not say. A team repo is not evidence of the whole stack.
    contribution_share: float | None = None

    commits: dict[str, Any] = Field(default_factory=dict)
    structure: dict[str, Any] = Field(default_factory=dict)
    judgment: dict[str, Any] = Field(default_factory=dict)
    skill_signals: list[dict[str, Any]] = Field(default_factory=list)

    # Real skill work, as opposed to notes, dotfiles or a README-only repo.
    skill_relevant: bool = False
    relevance: dict[str, Any] = Field(default_factory=dict)

    tree_truncated: bool = False


class ExternalContribution(BaseModel):
    """A PR opened against a repo the user does not own - strong Advanced signal."""

    repo: str
    html_url: str
    title: str | None = None
    state: str | None = None
    merged: bool = False
    created_at: str | None = None


class GitHubProfile(BaseModel):
    # Pseudonymous, stable, and the profile's filename. See generator/github/ids.py.
    applicant_id: str
    # Kept: repository URLs contain it, and the evidence agent must cite them.
    login: str
    html_url: str
    # Deliberately absent: name, bio, company, location, blog, avatar. They are
    # personal, and nothing downstream needs them to verify a skill.
    created_at: str | None = None
    account_age_days: int = 0
    public_repos: int = 0
    followers: int = 0
    following: int = 0

    repos: list[RepoRecord] = Field(default_factory=list)
    external_contributions: list[ExternalContribution] = Field(default_factory=list)

    languages_bytes: dict[str, int] = Field(default_factory=dict)
    total_commits: int = 0
    skill_evidence: list[SkillEvidence] = Field(default_factory=list)

    # Whether this profile carries enough evidence to verify claims against.
    # A user can pass the sampling criteria and still have eight empty forks.
    tier: str = "strict"       # "strict" | "relaxed" | "unusable"
    usability: dict[str, Any] = Field(default_factory=dict)

    # The search that found this person - NOT the slot they fill. Slots are
    # decided by assign.py from what the person builds; see data/githubs/corpus.json.
    search_stratum: str | None = None
    collected_at: str | None = None
    collector_version: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Relaxed or strict: eligible for a slot at all. Derived, so never stored."""
        return self.tier != "unusable"


class Candidate(BaseModel):
    login: str
    applicant_id: str | None = None   # assigned at first build; never changes
    html_url: str
    stratum: str
    query: str
    # "users" for the original user search, "repositories" for repository search.
    method: str = "users"
    found_via: str | None = None      # the repository whose owner this is
    discovered_at: str
    selected: bool = False
    reject_reason: str | None = None
    public_repos: int | None = None
    followers: int | None = None
    account_created_at: str | None = None
