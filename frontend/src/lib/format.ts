import { ApiError, BackendUnavailableError } from "./api";

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDateOnly(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return "—";
  return score.toFixed(1);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Turn any thrown error from the API client into a friendly, displayable message. */
export function describeError(err: unknown): string {
  if (err instanceof BackendUnavailableError) {
    return "Can't reach the backend right now. Please check your connection and try again.";
  }
  if (err instanceof ApiError) {
    if (err.code === "duplicate_email") {
      return "This email has already submitted an application.";
    }
    if (err.code === "validation_error") {
      return err.message || "Please check the form for errors.";
    }
    if (err.code === "role_full") {
      return "That role is already at capacity.";
    }
    if (err.code === "already_assigned") {
      return "This applicant already has an assignment in this run.";
    }
    if (err.code === "already_placed") {
      return "This applicant is already placed by an approved assignment elsewhere.";
    }
    if (err.code === "role_in_use") {
      return "This role can't be deleted because it's referenced by an assignment.";
    }
    if (err.code === "project_in_use") {
      return "This project can't be deleted because it's referenced by an assignment.";
    }
    return err.message || "Something went wrong.";
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Something went wrong.";
}
