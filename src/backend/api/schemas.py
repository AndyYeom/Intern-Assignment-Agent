"""HTTP request/response contracts. Separate from the agent and database models."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ApplicantStatus = Literal["submitted", "processing", "ready", "failed"]
RequirementType = Literal["hard_requirement", "preferred", "learning_opportunity"]
ProjectStatus = Literal["draft", "active", "archived"]
RunStatus = Literal["queued", "running", "completed", "failed"]
AssignmentStatus = Literal["proposed", "approved", "rejected"]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- errors -------------------------------------------------------------


class ErrorBody(ApiModel):
    code: str
    message: str
    details: list[dict[str, object]] | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody


# ---- applicant (public) -------------------------------------------------


class ApplicationCreated(ApiModel):
    id: uuid.UUID
    status: ApplicantStatus


class ApplicationPublic(ApiModel):
    """What an applicant may see about their own application."""

    id: uuid.UUID
    name: str
    status: ApplicantStatus
    submitted_at: datetime
    message: str


# ---- skills -------------------------------------------------------------


class SkillOut(ApiModel):
    id: str
    name: str
    category: str
    aliases: list[str]


# ---- applicants (manager) ------------------------------------------------


class AssignmentSummary(ApiModel):
    assignment_id: uuid.UUID
    run_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    role_id: uuid.UUID
    role_name: str
    status: AssignmentStatus
    score: float


class SkillBadge(ApiModel):
    skill_id: str
    name: str
    level: int


class ApplicantListItem(ApiModel):
    id: uuid.UUID
    reference: str
    name: str
    email: str
    github_url: str | None
    status: ApplicantStatus
    source: Literal["application", "legacy_import"]
    submitted_at: datetime
    skill_count: int
    top_skills: list[SkillBadge]
    assignment: AssignmentSummary | None


class DocumentOut(ApiModel):
    id: uuid.UUID
    document_type: Literal["resume", "portfolio"]
    original_filename: str
    mime_type: str
    size_bytes: int
    # Relative API path that streams the file.
    download_path: str


class EvidenceOut(ApiModel):
    source_type: Literal["resume", "portfolio", "github"]
    reference: str | None
    excerpt: str | None
    level: int | None


class ApplicantSkillOut(ApiModel):
    skill_id: str
    name: str
    category: str
    final_level: int
    claimed_level: int | None
    observed_level: int | None
    verification_status: str | None
    evidence_strength: str | None
    flag: str | None
    confidence: float | None
    claim_summary: str | None
    verification_summary: str | None
    evidence: list[EvidenceOut]


class ProcessingStage(ApiModel):
    run_id: uuid.UUID
    agent_type: Literal["profile", "github", "evidence", "resolve"]
    status: Literal["running", "succeeded", "failed", "skipped"]
    started_at: datetime
    completed_at: datetime | None
    message: str | None
    model: str | None
    # Small summary (counts, notes); the full output is fetched per run.
    details: dict[str, object] | None
    error: str | None
    has_output: bool


class AgentRunOut(ProcessingStage):
    output: dict[str, object] | None


class RoleScoreOut(ApiModel):
    run_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    role_id: uuid.UUID
    role_name: str
    candidate: bool
    fit_score: float
    growth_score: float


class ApplicantDetail(ApplicantListItem):
    portfolio_url: str | None
    github_login: str | None
    status_detail: str | None
    processed_at: datetime | None
    profile: dict[str, object] | None
    documents: list[DocumentOut]
    skills: list[ApplicantSkillOut]
    stages: list[ProcessingStage]
    # Scores from the most recent completed run that included this applicant.
    scores: list[RoleScoreOut]


# ---- projects -----------------------------------------------------------


class RequirementIn(ApiModel):
    skill_id: str
    required_level: int = Field(ge=1, le=3)
    requirement_type: RequirementType
    weight: float = Field(default=1.0, gt=0)


class RequirementOut(RequirementIn):
    skill_name: str


class RoleIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    capacity: int = Field(ge=1, le=50)
    requirements: list[RequirementIn] = Field(default_factory=list)


class RolePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=50)
    # When given, replaces the role's requirements.
    requirements: list[RequirementIn] | None = None


class RoleOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    capacity: int
    requirements: list[RequirementOut]


class ProjectIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: ProjectStatus = "active"
    roles: list[RoleIn] = Field(default_factory=list)


class ProjectPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ProjectStatus | None = None


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    status: ProjectStatus
    capacity: int
    roles: list[RoleOut]
    created_at: datetime
    updated_at: datetime


# ---- assignment runs ----------------------------------------------------


class RunCreate(ApiModel):
    # Omit to use every active project / every applicant with status "ready".
    project_ids: list[uuid.UUID] | None = None
    applicant_ids: list[uuid.UUID] | None = None
    seed: int = 42


class RunSummary(ApiModel):
    id: uuid.UUID
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    final_score: float | None
    applicant_count: int
    role_count: int
    assigned_count: int
    error: str | None


class Ref(ApiModel):
    id: uuid.UUID
    name: str


class AssignmentReason(ApiModel):
    """Deterministic explanation built from the requirements and final levels."""

    met: list[str]
    below: list[str]
    growth: list[str]
    summary: str


class AssignmentOut(ApiModel):
    id: uuid.UUID
    applicant: Ref
    project: Ref
    role: Ref
    solver_role: Ref
    overridden: bool
    score: float
    growth_score: float
    reason: AssignmentReason
    status: AssignmentStatus
    note: str | None
    updated_at: datetime


class UnassignedApplicant(ApiModel):
    id: uuid.UUID
    name: str
    candidate_role_count: int


class RoleUtilization(ApiModel):
    role_id: uuid.UUID
    role_name: str
    # Seats this run could fill (role capacity minus earlier approved placements).
    capacity: int
    filled: int
    # Seats already taken by approved placements from earlier runs.
    filled_before: int = 0


class ProjectUtilization(ApiModel):
    project_id: uuid.UUID
    project_name: str
    capacity: int
    filled: int
    filled_before: int = 0
    roles: list[RoleUtilization]


class RunDetail(RunSummary):
    configuration: dict[str, object]
    score_breakdown: dict[str, float] | None
    solver_details: dict[str, object] | None
    assignments: list[AssignmentOut]
    unassigned: list[UnassignedApplicant]
    utilization: list[ProjectUtilization]


class AssignmentPatch(ApiModel):
    status: AssignmentStatus | None = None
    # Move the applicant to another role in the same run (manager override).
    role_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


# ---- health -------------------------------------------------------------


class Health(ApiModel):
    status: Literal["ok"]


class Ready(ApiModel):
    status: Literal["ok", "unavailable"]
    database: bool

