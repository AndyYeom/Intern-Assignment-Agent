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

from typing import Literal

from pydantic import BaseModel, Field

# Career stage drives the shape of the resume, not just its wording.
#   student   - currently enrolled, no professional experience yet
#   intern    - enrolled, has done at least one internship
#   new_grad  - graduated within ~a year, first full-time role or seeking one
#   switcher  - changing field; bootcamp or self-taught, prior unrelated work
CareerStage = Literal["student", "intern", "new_grad", "switcher"]

# Which sections appear, in order, for each stage.
SECTION_ORDER: dict[str, list[str]] = {
    "student": ["education", "projects", "experience", "leadership", "skills"],
    "intern": ["education", "experience", "projects", "leadership", "skills"],
    "new_grad": ["education", "experience", "projects", "leadership", "skills"],
    "switcher": ["experience", "projects", "education", "leadership", "skills"],
}


class Education(BaseModel):
    school: str = "Massachusetts Institute of Technology"
    location: str = "Cambridge, MA"
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
    education: Education = Field(default_factory=Education)
    experience: list[Entry] = Field(default_factory=list)
    leadership: list[Entry] = Field(default_factory=list)
    objective: str | None = None
    photo: bool = True


class ResumeSpec(BaseModel):
    """A complete, renderable resume."""

    github_login: str
    first_name: str
    last_name: str
    career_stage: CareerStage = "student"
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github_url: str | None = None
    portfolio: str | None = None
    photo: bool = True

    objective: str | None = None
    education: Education = Field(default_factory=Education)
    experience: list[Entry] = Field(default_factory=list)
    projects: list[Entry] = Field(default_factory=list)
    leadership: list[Entry] = Field(default_factory=list)
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
