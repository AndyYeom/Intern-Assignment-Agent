import type {
  ApplicantDetail,
  ApplicantListItem,
  ApplicationCreated,
  ApplicationPublic,
  AgentRunOut,
  AssignmentOut,
  AssignmentPatch,
  ErrorResponse,
  ProjectIn,
  ProjectOut,
  ProjectPatch,
  RoleIn,
  RoleOut,
  RolePatch,
  RunCreate,
  RunDetail,
  RunSummary,
  SkillOut,
} from "./types";

/** Thrown for any error response the backend returns (4xx/5xx with a JSON error body). */
export class ApiError extends Error {
  code: string;
  details: Record<string, unknown>[] | null;
  status: number;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown>[] | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Thrown when the request never reached the backend (network failure, CORS, DNS, etc). */
export class BackendUnavailableError extends Error {
  constructor(message = "The backend is unavailable. Please try again shortly.") {
    super(message);
    this.name = "BackendUnavailableError";
  }
}

function joinUrl(base: string, path: string): string {
  return `${base.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}

async function parseErrorBody(res: Response): Promise<{ code: string; message: string; details: Record<string, unknown>[] | null }> {
  try {
    const body = (await res.json()) as ErrorResponse;
    if (body?.error?.code && body?.error?.message) {
      return body.error;
    }
  } catch {
    // fall through to generic error below
  }
  return {
    code: "unknown_error",
    message: `Request failed with status ${res.status}`,
    details: null,
  };
}

async function request<T>(
  baseUrl: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(joinUrl(baseUrl, path), init);
  } catch {
    throw new BackendUnavailableError();
  }

  if (!res.ok) {
    const { code, message, details } = await parseErrorBody(res);
    throw new ApiError(res.status, code, message, details);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export interface SubmitApplicationInput {
  name: string;
  email: string;
  github_url: string;
  portfolio_url?: string;
  resume: File;
}

export function createApiClient(baseUrl: string) {
  return {
    baseUrl,

    // ---- public applicant endpoints ----
    async submitApplication(
      input: SubmitApplicationInput,
    ): Promise<ApplicationCreated> {
      const form = new FormData();
      form.append("name", input.name);
      form.append("email", input.email);
      form.append("github_url", input.github_url);
      if (input.portfolio_url) {
        form.append("portfolio_url", input.portfolio_url);
      }
      form.append("resume", input.resume);
      return request<ApplicationCreated>(baseUrl, "/api/applications", {
        method: "POST",
        body: form,
      });
    },

    async getApplication(id: string): Promise<ApplicationPublic> {
      return request<ApplicationPublic>(baseUrl, `/api/applications/${id}`);
    },

    // ---- manager: applicants ----
    async listApplicants(params?: {
      status?: string;
      q?: string;
      placement?: "assigned" | "unassigned";
    }): Promise<ApplicantListItem[]> {
      const search = new URLSearchParams();
      if (params?.status) search.set("status", params.status);
      if (params?.placement) search.set("placement", params.placement);
      if (params?.q) search.set("q", params.q);
      const qs = search.toString();
      return request<ApplicantListItem[]>(
        baseUrl,
        `/api/manager/applicants${qs ? `?${qs}` : ""}`,
      );
    },

    async getApplicant(id: string): Promise<ApplicantDetail> {
      return request<ApplicantDetail>(baseUrl, `/api/manager/applicants/${id}`);
    },

    async reprocessApplicant(id: string): Promise<ApplicationCreated> {
      return request<ApplicationCreated>(
        baseUrl,
        `/api/manager/applicants/${id}/reprocess`,
        { method: "POST" },
      );
    },

    async reverifyGithub(id: string): Promise<ApplicationCreated> {
      return request<ApplicationCreated>(
        baseUrl,
        `/api/manager/applicants/${id}/reverify-github`,
        { method: "POST" },
      );
    },

    async getAgentRun(applicantId: string, runId: string): Promise<AgentRunOut> {
      return request<AgentRunOut>(
        baseUrl,
        `/api/manager/applicants/${applicantId}/agent-runs/${runId}`,
      );
    },

    // ---- manager: skills ----
    async listSkills(): Promise<SkillOut[]> {
      return request<SkillOut[]>(baseUrl, "/api/manager/skills");
    },

    // ---- manager: projects ----
    async listProjects(): Promise<ProjectOut[]> {
      return request<ProjectOut[]>(baseUrl, "/api/manager/projects");
    },

    async getProject(id: string): Promise<ProjectOut> {
      return request<ProjectOut>(baseUrl, `/api/manager/projects/${id}`);
    },

    async createProject(body: ProjectIn): Promise<ProjectOut> {
      return request<ProjectOut>(
        baseUrl,
        "/api/manager/projects",
        jsonInit("POST", body),
      );
    },

    async patchProject(id: string, body: ProjectPatch): Promise<ProjectOut> {
      return request<ProjectOut>(
        baseUrl,
        `/api/manager/projects/${id}`,
        jsonInit("PATCH", body),
      );
    },

    async createRole(projectId: string, body: RoleIn): Promise<RoleOut> {
      return request<RoleOut>(
        baseUrl,
        `/api/manager/projects/${projectId}/roles`,
        jsonInit("POST", body),
      );
    },

    async patchRole(roleId: string, body: RolePatch): Promise<RoleOut> {
      return request<RoleOut>(
        baseUrl,
        `/api/manager/roles/${roleId}`,
        jsonInit("PATCH", body),
      );
    },

    async deleteRole(roleId: string): Promise<void> {
      return request<void>(baseUrl, `/api/manager/roles/${roleId}`, {
        method: "DELETE",
      });
    },

    // ---- manager: assignment runs ----
    async listRuns(): Promise<RunSummary[]> {
      return request<RunSummary[]>(baseUrl, "/api/manager/assignment-runs");
    },

    async createRun(body: RunCreate): Promise<RunSummary> {
      return request<RunSummary>(
        baseUrl,
        "/api/manager/assignment-runs",
        jsonInit("POST", body),
      );
    },

    async getRun(id: string): Promise<RunDetail> {
      return request<RunDetail>(baseUrl, `/api/manager/assignment-runs/${id}`);
    },

    async patchAssignment(
      id: string,
      body: AssignmentPatch,
    ): Promise<AssignmentOut> {
      return request<AssignmentOut>(
        baseUrl,
        `/api/manager/assignments/${id}`,
        jsonInit("PATCH", body),
      );
    },

    downloadUrl(relativePath: string): string {
      return joinUrl(baseUrl, relativePath);
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
