"""PostgreSQL schema: the system of record for structured application state.

Proficiency uses the pipeline's shared 1-3 scale (resources/proficiency_levels.md):
1 Entry, 2 Intermediate, 3 Advanced. Skills are keyed by their taxonomy id
(resources/taxonomy.json), the identifier every agent already uses.

Roles are first-class here even though the matching engine only knows
"projects": each project role is handed to the optimizer as its own matching
unit (see services/assignment.py).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

APPLICANT_STATUSES = ("submitted", "processing", "ready", "failed")
DOCUMENT_TYPES = ("resume", "portfolio")
VERIFICATION_STATUSES = ("verified", "partially_verified", "not_observed", "conflicting")
REQUIREMENT_TYPES = ("hard_requirement", "preferred", "learning_opportunity")
PROJECT_STATUSES = ("draft", "active", "archived")
RUN_STATUSES = ("queued", "running", "completed", "failed")
ASSIGNMENT_STATUSES = ("proposed", "approved", "rejected")
AGENT_RUN_STATUSES = ("running", "succeeded", "failed", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("uq_skills_name_lower", func.lower(name), unique=True),)


class Applicant(TimestampMixin, Base):
    __tablename__ = "applicants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Identifier used by the agent pipeline and legacy data, e.g. applicant0001.
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    github_url: Mapped[str | None] = mapped_column(String(300))
    github_login: Mapped[str | None] = mapped_column(String(100))
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    # Short, applicant-safe reason for a failure. Never a stack trace.
    status_detail: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="application")
    # Display-only profile context from the profile agent: domains, interests,
    # education, work experience.
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Snapshot of the collected GitHub profile, so a fresh container can
    # rebuild the evidence agent's input file.
    github_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    documents: Mapped[list["ApplicantDocument"]] = relationship(
        back_populates="applicant", cascade="all, delete-orphan", order_by="ApplicantDocument.created_at"
    )
    skills: Mapped[list["ApplicantSkill"]] = relationship(
        back_populates="applicant", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(_in("status", APPLICANT_STATUSES), name="ck_applicants_status"),
        CheckConstraint(_in("source", ("application", "legacy_import")), name="ck_applicants_source"),
        Index("uq_applicants_email_lower", func.lower(email), unique=True),
        Index("ix_applicants_status", "status"),
    )


class ApplicantDocument(Base):
    __tablename__ = "applicant_documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applicants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Opaque storage key (LocalStorage path today, S3 object key later).
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    applicant: Mapped[Applicant] = relationship(back_populates="documents")

    __table_args__ = (
        CheckConstraint(_in("document_type", DOCUMENT_TYPES), name="ck_documents_type"),
    )


class ApplicantSkill(Base):
    """One resolved skill: the resume claim, GitHub verification and final level."""

    __tablename__ = "applicant_skills"

    id: Mapped[uuid.UUID] = _uuid_pk()
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applicants.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), nullable=False, index=True)
    claimed_level: Mapped[int | None] = mapped_column(SmallInteger)
    observed_level: Mapped[int | None] = mapped_column(SmallInteger)
    # Output of pipeline/resolve_profile.py; this is what scoring uses. 0 means
    # the claim was contradicted by GitHub evidence (resolve_profile takes the lower).
    final_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    verification_status: Mapped[str | None] = mapped_column(String(24))
    evidence_strength: Mapped[str | None] = mapped_column(String(12))
    # resolve_profile flag: "unverified" or "conflicting".
    flag: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    # Short persisted justifications written by the agents (not chain-of-thought).
    claim_summary: Mapped[str | None] = mapped_column(Text)
    verification_summary: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(String(10))

    applicant: Mapped[Applicant] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()
    evidence: Mapped[list["ApplicantSkillEvidence"]] = relationship(
        back_populates="applicant_skill", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("applicant_id", "skill_id", name="uq_applicant_skills"),
        CheckConstraint("final_level BETWEEN 0 AND 3", name="ck_applicant_skills_final"),
        CheckConstraint(
            "claimed_level IS NULL OR claimed_level BETWEEN 1 AND 3",
            name="ck_applicant_skills_claimed",
        ),
        CheckConstraint(
            "observed_level IS NULL OR observed_level BETWEEN 0 AND 3",
            name="ck_applicant_skills_observed",
        ),
        CheckConstraint(
            "verification_status IS NULL OR " + _in("verification_status", VERIFICATION_STATUSES),
            name="ck_applicant_skills_status",
        ),
    )


class ApplicantSkillEvidence(Base):
    __tablename__ = "applicant_skill_evidence"

    id: Mapped[uuid.UUID] = _uuid_pk()
    applicant_skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applicant_skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Repository URL for GitHub, page number/label for documents.
    reference: Mapped[str | None] = mapped_column(String(500))
    excerpt: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int | None] = mapped_column(SmallInteger)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    applicant_skill: Mapped[ApplicantSkill] = relationship(back_populates="evidence")

    __table_args__ = (
        CheckConstraint(_in("source_type", ("resume", "portfolio", "github")), name="ck_evidence_source"),
    )


class AgentRun(Base):
    """Audit record of one pipeline stage for one applicant. No prompts or model reasoning."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    applicant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applicants.id", ondelete="CASCADE"), index=True
    )
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    model: Mapped[str | None] = mapped_column(String(200))
    # Structured agent output kept for traceability (e.g. the ApplicantProfile).
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(_in("status", AGENT_RUN_STATUSES), name="ck_agent_runs_status"),
        CheckConstraint(
            _in("agent_type", ("profile", "github", "evidence", "resolve")),
            name="ck_agent_runs_type",
        ),
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    roles: Mapped[list["ProjectRole"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectRole.position"
    )

    __table_args__ = (
        CheckConstraint(_in("status", PROJECT_STATUSES), name="ck_projects_status"),
        Index("uq_projects_name_lower", func.lower(name), unique=True),
    )


class ProjectRole(TimestampMixin, Base):
    __tablename__ = "project_roles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped[Project] = relationship(back_populates="roles")
    requirements: Mapped[list["ProjectRoleSkill"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", order_by="ProjectRoleSkill.skill_id"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_roles_name"),
        CheckConstraint("capacity >= 1", name="ck_project_roles_capacity"),
    )


class ProjectRoleSkill(Base):
    __tablename__ = "project_role_skills"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_roles.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), primary_key=True)
    required_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Same values as the matching engine's RequirementType.
    requirement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    role: Mapped[ProjectRole] = relationship(back_populates="requirements")
    skill: Mapped[Skill] = relationship()

    __table_args__ = (
        CheckConstraint("required_level BETWEEN 1 AND 3", name="ck_role_skills_level"),
        CheckConstraint(_in("requirement_type", REQUIREMENT_TYPES), name="ck_role_skills_type"),
        CheckConstraint("weight > 0", name="ck_role_skills_weight"),
    )


class AssignmentRun(Base):
    __tablename__ = "assignment_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    # Inputs as given: included projects/applicants and optimizer settings.
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    solver_version: Mapped[str] = mapped_column(String(40), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(40), nullable=False)
    final_score: Mapped[float | None] = mapped_column(Float)
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Optimizer diagnostics: generations, stop reason.
    solver_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_assignment_runs_status"),
    )


class ApplicantRoleScore(Base):
    """Pairwise score for one applicant and one project role within a run."""

    __tablename__ = "applicant_role_scores"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assignment_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment_runs.id", ondelete="CASCADE"), nullable=False
    )
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applicants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    project_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_roles.id", ondelete="RESTRICT"), nullable=False
    )
    candidate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    growth_score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "assignment_run_id", "applicant_id", "project_role_id", name="uq_role_scores_pair"
        ),
    )


class Assignment(TimestampMixin, Base):
    """A placement proposed by a run. The solver's choice is never overwritten:
    a manager override changes project_role_id and keeps solver_role_id."""

    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assignment_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment_runs.id", ondelete="CASCADE"), nullable=False
    )
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applicants.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    project_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_roles.id", ondelete="RESTRICT"), nullable=False
    )
    solver_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_roles.id", ondelete="RESTRICT"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="proposed")
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("assignment_run_id", "applicant_id", name="uq_assignments_run_applicant"),
        CheckConstraint(_in("status", ASSIGNMENT_STATUSES), name="ck_assignments_status"),
        Index("ix_assignments_run", "assignment_run_id"),
    )
