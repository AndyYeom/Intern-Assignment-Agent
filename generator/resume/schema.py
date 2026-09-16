"""Schemas for synthetic resumes in the MIT CAPD format.

Deliberate split of responsibility:

  * `ResumeInfo`  - the *identity* a human or an authoring agent supplies:
                    name, contact, school, major, grad date. Never derivable
                    from GitHub.
  * `ResumeSpec`  - the full resume, auto-drafted from a GitHubProfile and then
                    freely edited by the authoring agent.

The renderer never invents claims and never checks them. Whoever fills the spec
decides what it says - which is what keeps the planted-exaggeration experiment
honest: agent A authors the claims, agent C verifies them independently.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Domains that can never belong to a real person or organisation.
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".example.com", ".example.org",
                     ".example.net")
RESERVED_HOSTS = {"example.com", "example.org", "example.net"}
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")

# Career stage drives the shape of the resume, not just its wording.
#   student   - currently enrolled, no professional experience yet
#   intern    - enrolled, has done at least one internship
#   new_grad  - graduated within ~a year, first full-time role or seeking one
#   switcher  - changing field; bootcamp or self-taught, prior unrelated work
CareerStage = Literal["student", "intern", "new_grad", "switcher"]

# Which sections appear, in order, for each stage.
SECTION_ORDER: dict[str, list[str]] = {
    "student": ["education", "projects", "experience", "leadership", "awards", "skills"],
    "intern": ["education", "experience", "projects", "leadership", "awards", "skills"],
    "new_grad": ["education", "experience", "projects", "leadership", "awards", "skills"],
    "switcher": ["experience", "projects", "education", "leadership", "awards", "skills"],
}


class Education(BaseModel):
    # Fictional on purpose: synthetic applicants must not name real institutions.
    school: str = "Northbridge Institute of Technology"
    location: str = "Port Calder"
    degree: str = "Bachelor of Science"
    major: str = ""
    minor: str | None = None
    graduation: str = ""            # "June 2026"
    gpa: str | None = None
    coursework: list[str] = Field(default_factory=list)
    honors: list[str] = Field(default_factory=list)


class Entry(BaseModel):
    """One dated block under Experience, Projects or Leadership."""

    title: str
    organization: str | None = None
    location: str | None = None
    start: str = ""                 # "Jun 2024"
    end: str = "Present"
    bullets: list[str] = Field(default_factory=list)
    link: str | None = None
    tech: list[str] = Field(default_factory=list)


class ResumeInfo(BaseModel):
    """The identity half - supplied per person, not derived from GitHub."""

    github_login: str
    first_name: str
    last_name: str
    career_stage: CareerStage = "student"
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    portfolio: str | None = None
    # The handle printed on the resume. Never the real login - a fabricated
    # person must not link to a real stranger's account. Defaults to a slug of
    # the invented name; the real login stays in the manifest for the evidence
    # agent.
    github_handle: str | None = None
    education: Education = Field(default_factory=Education)
    experience: list[Entry] = Field(default_factory=list)
    leadership: list[Entry] = Field(default_factory=list)
    objective: str | None = None
    photo: bool = False   # MIT Template A has no photo


class ResumeSpec(BaseModel):
    """A complete, renderable resume."""

    github_login: str
    # The pseudonymous ID of the profile this resume was drafted from.
    applicant_id: str | None = None
    first_name: str
    last_name: str
    career_stage: CareerStage = "student"
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github_url: str | None = None
    portfolio: str | None = None
    photo: bool = False   # MIT Template A has no photo

    objective: str | None = None
    education: Education = Field(default_factory=Education)
    experience: list[Entry] = Field(default_factory=list)
    projects: list[Entry] = Field(default_factory=list)
    leadership: list[Entry] = Field(default_factory=list)
    awards: list[Entry] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)

    # Provenance - never rendered, kept so the corpus stays auditable.
    authored_by: str | None = None
    drafted_from_profile: bool = False
    batch: int | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def sections(self) -> list[str]:
        return SECTION_ORDER.get(self.career_stage, SECTION_ORDER["student"])

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def slug(self) -> str:
        return f"{self.first_name}-{self.last_name}".lower().replace(" ", "-")


class GenRequest(BaseModel):
    """What `generator re gen` needs to produce one resume.

    Field order follows MIT Resume Template A, top to bottom. Only the identity
    and the applicant are required: projects and skills are drafted from the
    person's real GitHub evidence when omitted. A spec file written by a previous
    `gen` is also a valid request: extra fields are ignored, and its projects and
    skills are kept.
    """

    # Which GitHub profile this resume pairs with. Required.
    applicant_id: str

    # Header: name and contact line.
    first_name: str
    last_name: str
    location: str | None = None
    phone: str | None = None
    email: str | None = None
    linkedin: str | None = None
    portfolio: str | None = None
    github_handle: str | None = None

    career_stage: CareerStage = "student"
    objective: str | None = None
    photo: bool = False

    # Sections, in template order.
    education: Education = Field(default_factory=Education)
    experience: list[Entry] = Field(default_factory=list)
    projects: list[Entry] | None = None          # None = draft from GitHub
    leadership: list[Entry] = Field(default_factory=list)
    awards: list[Entry] = Field(default_factory=list)
    skills: dict[str, list[str]] | None = None   # None = draft from GitHub

    # Present in spec files; checked against applicant_id, never trusted over it.
    github_login: str | None = None

    @field_validator("email", "linkedin", "portfolio", mode="before")
    @classmethod
    def _unwrap_markdown(cls, value: object) -> object:
        """Chat interfaces turn emails and URLs into Markdown links, and copying the
        rendered reply copies that syntax: `[a@b.example](mailto:a@b.example)`."""
        if not isinstance(value, str):
            return value
        text: str = value.strip()
        link = MARKDOWN_LINK.fullmatch(text)
        if link:
            text = link.group(1)
        return re.sub(r"^mailto:", "", text, flags=re.IGNORECASE)

    @field_validator("email", "linkedin", "portfolio")
    @classmethod
    def _reserved_domain(cls, value: str | None) -> str | None:
        """Contact details must be unable to reach a real person.

        A plausible invented address or profile URL can belong to someone real, so
        only domains reserved for examples are accepted (RFC 2606 / RFC 6761).
        """
        if not value:
            return value
        host = value.rsplit("@", 1)[-1] if "@" in value else value
        host = re.sub(r"^https?://", "", host).split("/", 1)[0].lower()
        if not HOST.fullmatch(host):
            raise ValueError(f"{value!r} is not a plain email address or URL")
        if host.endswith(RESERVED_SUFFIXES) or host in RESERVED_HOSTS:
            return value
        raise ValueError(
            f"{value!r} uses a real domain ({host}); use a reserved one such as "
            "northbridge.example, example.com or linkedin.example.com")
