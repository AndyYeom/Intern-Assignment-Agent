import { Badge } from "@mantine/core";
import type {
  ApplicantStatus,
  AssignmentStatus,
  ProjectStatus,
  RunStatus,
} from "@/lib/types";

const APPLICANT_COLORS: Record<ApplicantStatus, string> = {
  submitted: "blue",
  processing: "yellow",
  ready: "green",
  failed: "red",
};

const RUN_COLORS: Record<RunStatus, string> = {
  queued: "gray",
  running: "yellow",
  completed: "green",
  failed: "red",
};

const ASSIGNMENT_COLORS: Record<AssignmentStatus, string> = {
  proposed: "blue",
  approved: "green",
  rejected: "red",
};

const PROJECT_COLORS: Record<ProjectStatus, string> = {
  draft: "gray",
  active: "green",
  archived: "dark",
};

export function ApplicantStatusBadge({ status }: { status: ApplicantStatus }) {
  return (
    <Badge color={APPLICANT_COLORS[status]} variant="light">
      {status}
    </Badge>
  );
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge color={RUN_COLORS[status]} variant="light">
      {status}
    </Badge>
  );
}

export function AssignmentStatusBadge({
  status,
}: {
  status: AssignmentStatus;
}) {
  return (
    <Badge color={ASSIGNMENT_COLORS[status]} variant="light">
      {status}
    </Badge>
  );
}

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  return (
    <Badge color={PROJECT_COLORS[status]} variant="light">
      {status}
    </Badge>
  );
}

const VERIFICATION_LABELS: Record<string, string> = {
  verified: "Verified",
  partially_verified: "Partially verified",
  not_observed: "Not observed",
  conflicting: "Conflicting",
};

const VERIFICATION_COLORS: Record<string, string> = {
  verified: "green",
  partially_verified: "yellow",
  not_observed: "gray",
  conflicting: "red",
};

export function VerificationBadge({ status }: { status: string | null }) {
  if (!status) {
    return (
      <Badge color="gray" variant="light">
        Unknown
      </Badge>
    );
  }
  return (
    <Badge color={VERIFICATION_COLORS[status] ?? "gray"} variant="light">
      {VERIFICATION_LABELS[status] ?? status}
    </Badge>
  );
}
