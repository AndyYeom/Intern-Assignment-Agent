/**
 * TypeScript mirror of src/backend/api/schemas.py.
 * Keep in sync with the backend Pydantic models.
 */

export type ApplicantStatus = "submitted" | "processing" | "ready" | "failed";
export type RequirementType =
  | "hard_requirement"
  | "preferred"
  | "learning_opportunity";
export type ProjectStatus = "draft" | "active" | "archived";
export type RunStatus = "queued" | "running" | "completed" | "failed";
export type AssignmentStatus = "proposed" | "approved" | "rejected";

// ---- errors ---------------------------------------------------------------

export interface ErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>[] | null;
}

export interface ErrorResponse {
  error: ErrorBody;
}

// ---- applicant (public) ----------------------------------------------------

export interface ApplicationCreated {
  id: string;
  status: ApplicantStatus;
}

export interface ApplicationPublic {
  id: string;
  name: string;
  status: ApplicantStatus;
  submitted_at: string;
  message: string;
}

// ---- skills -----------------------------------------------------------------

export interface SkillOut {
  id: string;
  name: string;
  category: string;
  aliases: string[];
}

// ---- applicants (manager) ----------------------------------------------------

export interface AssignmentSummary {
  assignment_id: string;
  run_id: string;
  project_id: string;
  project_name: string;
  role_id: string;
  role_name: string;
  status: AssignmentStatus;
  score: number;
}

export interface SkillBadge {
  skill_id: string;
  name: string;
  level: number;
}

export interface ApplicantListItem {
  id: string;
  reference: string;
  name: string;
  email: string;
  github_url: string | null;
  status: ApplicantStatus;
  source: "application" | "legacy_import";
  submitted_at: string;
  skill_count: number;
  top_skills: SkillBadge[];
  assignment: AssignmentSummary | null;
}

export interface DocumentOut {
  id: string;
  document_type: "resume" | "portfolio";
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  download_path: string;
}

export interface EvidenceOut {
  source_type: "resume" | "portfolio" | "github";
  reference: string | null;
  excerpt: string | null;
  level: number | null;
}

export interface ApplicantSkillOut {
  skill_id: string;
  name: string;
  category: string;
  final_level: number;
  claimed_level: number | null;
  observed_level: number | null;
  verification_status: string | null;
  evidence_strength: string | null;
  flag: string | null;
  confidence: number | null;
  claim_summary: string | null;
  verification_summary: string | null;
  evidence: EvidenceOut[];
}

export type AgentType = "profile" | "github" | "evidence" | "resolve";

export interface ProcessingStage {
  run_id: string;
  agent_type: AgentType;
  status: "running" | "succeeded" | "failed" | "skipped";
  started_at: string;
  completed_at: string | null;
  message: string | null;
  model: string | null;
  details: Record<string, unknown> | null;
  error: string | null;
  has_output: boolean;
}

export interface AgentRunOut extends ProcessingStage {
  output: Record<string, unknown> | null;
}

export interface RoleScoreOut {
  run_id: string;
  project_id: string;
  project_name: string;
  role_id: string;
  role_name: string;
  candidate: boolean;
  fit_score: number;
  growth_score: number;
}

export interface ApplicantDetail extends ApplicantListItem {
  portfolio_url: string | null;
  github_login: string | null;
  status_detail: string | null;
  processed_at: string | null;
  profile: Record<string, unknown> | null;
  documents: DocumentOut[];
  skills: ApplicantSkillOut[];
  stages: ProcessingStage[];
  scores: RoleScoreOut[];
}

// ---- projects -----------------------------------------------------------------

export interface RequirementIn {
  skill_id: string;
  required_level: number;
  requirement_type: RequirementType;
  weight: number;
}

export interface RequirementOut extends RequirementIn {
  skill_name: string;
}

export interface RoleIn {
  name: string;
  description: string;
  capacity: number;
  requirements: RequirementIn[];
}

export interface RolePatch {
  name?: string | null;
  description?: string | null;
  capacity?: number | null;
  requirements?: RequirementIn[] | null;
}

export interface RoleOut {
  id: string;
  name: string;
  description: string;
  capacity: number;
  requirements: RequirementOut[];
}

export interface ProjectIn {
  name: string;
  description: string;
  status: ProjectStatus;
  roles: RoleIn[];
}

export interface ProjectPatch {
  name?: string | null;
  description?: string | null;
  status?: ProjectStatus | null;
}

export interface ProjectOut {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  capacity: number;
  roles: RoleOut[];
  created_at: string;
  updated_at: string;
}

// ---- assignment runs ----------------------------------------------------------

export interface RunCreate {
  project_ids?: string[] | null;
  applicant_ids?: string[] | null;
  seed?: number;
}

export interface RunSummary {
  id: string;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  final_score: number | null;
  applicant_count: number;
  role_count: number;
  assigned_count: number;
  error: string | null;
}

export interface Ref {
  id: string;
  name: string;
}

export interface AssignmentReason {
  met: string[];
  below: string[];
  growth: string[];
  summary: string;
}

export interface AssignmentOut {
  id: string;
  applicant: Ref;
  project: Ref;
  role: Ref;
  solver_role: Ref;
  overridden: boolean;
  score: number;
  growth_score: number;
  reason: AssignmentReason;
  status: AssignmentStatus;
  note: string | null;
  updated_at: string;
}

export interface UnassignedApplicant {
  id: string;
  name: string;
  candidate_role_count: number;
}

export interface RoleUtilization {
  role_id: string;
  role_name: string;
  capacity: number;
  filled: number;
}

export interface ProjectUtilization {
  project_id: string;
  project_name: string;
  capacity: number;
  filled: number;
  roles: RoleUtilization[];
}

export interface RunDetail extends RunSummary {
  configuration: Record<string, unknown>;
  score_breakdown: Record<string, number> | null;
  solver_details: Record<string, unknown> | null;
  assignments: AssignmentOut[];
  unassigned: UnassignedApplicant[];
  utilization: ProjectUtilization[];
}

export interface AssignmentPatch {
  status?: AssignmentStatus | null;
  role_id?: string | null;
  note?: string | null;
}

// ---- health ---------------------------------------------------------------------

export interface Health {
  status: "ok";
}

export interface Ready {
  status: "ok" | "unavailable";
  database: boolean;
}

// ---- UI helper labels -------------------------------------------------------------

export const PROFICIENCY_LABELS: Record<number, string> = {
  1: "Entry",
  2: "Intermediate",
  3: "Advanced",
};

export const REQUIREMENT_TYPE_LABELS: Record<RequirementType, string> = {
  hard_requirement: "Required",
  preferred: "Preferred",
  learning_opportunity: "Learning opportunity",
};
