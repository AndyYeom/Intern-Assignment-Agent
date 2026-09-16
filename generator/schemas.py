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

    commits: dict[str, Any] = Field(default_factory=dict)
    structure: dict[str, Any] = Field(default_factory=dict)
    judgment: dict[str, Any] = Field(default_factory=dict)
    skill_signals: list[dict[str, Any]] = Field(default_factory=list)

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
    login: str
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    location: str | None = None
    blog: str | None = None
    html_url: str
    avatar_url: str | None = None
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

    stratum: str | None = None
    collected_at: str | None = None
    collector_version: str | None = None
    notes: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    login: str
    html_url: str
    stratum: str
    query: str
    discovered_at: str
    selected: bool = False
    reject_reason: str | None = None
    public_repos: int | None = None
    followers: int | None = None
    account_created_at: str | None = None
