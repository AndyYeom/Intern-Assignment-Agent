"use client";

import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  CopyButton,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Text,
  Timeline,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  AlertTriangle,
  Braces,
  FileText,
  GitBranch,
  ListChecks,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useApi } from "@/lib/api-context";
import { describeError } from "@/lib/format";
import type {
  AgentRunOut,
  AgentType,
  ApplicantStatus,
  ProcessingStage,
} from "@/lib/types";

const STAGES: {
  type: AgentType;
  title: string;
  description: string;
  icon: typeof FileText;
}[] = [
  {
    type: "profile",
    title: "Profile agent",
    description: "Resume PDF → claimed skills, education, experience (LLM)",
    icon: FileText,
  },
  {
    type: "github",
    title: "GitHub collector",
    description: "Public repositories, languages and commits of the GitHub profile",
    icon: GitBranch,
  },
  {
    type: "evidence",
    title: "Evidence agent",
    description: "Checks each claimed skill against the GitHub data (rules + LLM)",
    icon: ShieldCheck,
  },
  {
    type: "resolve",
    title: "Skill resolution",
    description: "Claimed vs observed levels → final skill levels stored for matching",
    icon: ListChecks,
  },
];

const STATUS_COLOR: Record<string, string> = {
  succeeded: "green",
  running: "yellow",
  failed: "red",
  skipped: "orange",
  pending: "gray",
  "not run": "gray",
};

export function AgentPipeline({
  applicantId,
  applicantStatus,
  stages,
  onChanged,
}: {
  applicantId: string;
  applicantStatus: ApplicantStatus;
  stages: ProcessingStage[];
  onChanged: () => Promise<void> | void;
}) {
  const api = useApi();
  const [viewing, setViewing] = useState<ProcessingStage | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const byType = new Map(stages.map((s) => [s.agent_type, s]));
  const busy = applicantStatus === "submitted" || applicantStatus === "processing";
  const github = byType.get("github");
  const evidence = byType.get("evidence");
  const githubIncomplete =
    github?.status === "skipped" ||
    github?.status === "failed" ||
    evidence?.status === "failed";

  async function handleRerun() {
    setRerunning(true);
    try {
      await api.reverifyGithub(applicantId);
      notifications.show({
        title: "GitHub verification started",
        message: "GitHub, evidence and resolution are running again.",
        color: "blue",
      });
      await onChanged();
    } catch (err) {
      setRefusal(describeError(err));
    } finally {
      setRerunning(false);
    }
  }

  const lastDone = STAGES.reduce(
    (acc, s, i) => (byType.has(s.type) ? i : acc),
    -1,
  );

  return (
    <Card withBorder radius="md" p="md">
      <Group justify="space-between" mb="md">
        <Title order={4}>Agent pipeline</Title>
        {githubIncomplete && !busy && (
          <Button
            size="xs"
            variant="light"
            leftSection={<RefreshCw size={14} />}
            loading={rerunning}
            onClick={handleRerun}
          >
            Rerun GitHub verification
          </Button>
        )}
      </Group>

      {stages.length === 0 && !busy ? (
        <Text size="sm" c="dimmed">
          No agent runs recorded for this applicant (imported records were
          processed before this system existed).
        </Text>
      ) : (
        <Timeline active={lastDone} bulletSize={28} lineWidth={2}>
          {STAGES.map(({ type, title, description, icon: Icon }) => {
            const stage = byType.get(type);
            const status = stage?.status ?? (busy ? "pending" : "not run");
            return (
              <Timeline.Item
                key={type}
                bullet={<Icon size={14} />}
                color={STATUS_COLOR[status]}
                title={
                  <Group gap="xs">
                    <Text fw={500} size="sm">
                      {title}
                    </Text>
                    <Badge size="sm" variant="light" color={STATUS_COLOR[status]}>
                      {status === "running" ? (
                        <Group gap={4} wrap="nowrap">
                          <Loader size={8} color="yellow" /> running
                        </Group>
                      ) : (
                        status
                      )}
                    </Badge>
                    {stage && (
                      <Text size="xs" c="dimmed">
                        {duration(stage)}
                        {stage.model ? ` · ${stage.model}` : ""}
                      </Text>
                    )}
                  </Group>
                }
              >
                <Text size="xs" c="dimmed">
                  {description}
                </Text>
                {stage?.message && (
                  <Text size="sm" mt={4}>
                    {stage.message}
                  </Text>
                )}
                {stage?.details && <DetailChips details={stage.details} />}
                {stage?.error && (
                  <Alert
                    mt={6}
                    p="xs"
                    color="red"
                    variant="light"
                    icon={<AlertTriangle size={14} />}
                  >
                    <Text size="xs" style={{ wordBreak: "break-word" }}>
                      {stage.error}
                    </Text>
                  </Alert>
                )}
                {stage && (stage.has_output || stage.details) && (
                  <Button
                    mt={6}
                    size="compact-xs"
                    variant="subtle"
                    leftSection={<Braces size={12} />}
                    onClick={() => setViewing(stage)}
                  >
                    View JSON
                  </Button>
                )}
              </Timeline.Item>
            );
          })}
        </Timeline>
      )}

      <RunJsonModal
        applicantId={applicantId}
        stage={viewing}
        onClose={() => setViewing(null)}
      />

      <Modal
        opened={refusal !== null}
        onClose={() => setRefusal(null)}
        title="Can't rerun GitHub verification"
        centered
      >
        <Stack>
          <Text size="sm">{refusal}</Text>
          <Group justify="flex-end">
            <Button onClick={() => setRefusal(null)}>OK</Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

function DetailChips({ details }: { details: Record<string, unknown> }) {
  const chips = Object.entries(details).filter(
    ([key, value]) =>
      key !== "note" && (typeof value === "number" || typeof value === "string"),
  );
  const counts = details.status_counts;
  if (counts && typeof counts === "object") {
    for (const [k, v] of Object.entries(counts as Record<string, unknown>)) {
      chips.push([k, v]);
    }
  }
  const unmapped = details.unmapped;
  if (Array.isArray(unmapped) && unmapped.length > 0) {
    chips.push(["unmapped", unmapped.length]);
  }
  if (chips.length === 0) return null;
  return (
    <Group gap={6} mt={4}>
      {chips.map(([k, v]) => (
        <Badge key={k} size="xs" variant="outline" color="gray" tt="none">
          {k.replaceAll("_", " ")}: {String(v)}
        </Badge>
      ))}
    </Group>
  );
}

function RunJsonModal({
  applicantId,
  stage,
  onClose,
}: {
  applicantId: string;
  stage: ProcessingStage | null;
  onClose: () => void;
}) {
  const api = useApi();
  const [result, setResult] = useState<{
    runId: string;
    run?: AgentRunOut;
    error?: string;
  } | null>(null);
  const runId = stage?.run_id ?? null;

  // Fetch the full run (with its output) when a run is opened.
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    api
      .getAgentRun(applicantId, runId)
      .then((run) => !cancelled && setResult({ runId, run }))
      .catch((err) => !cancelled && setResult({ runId, error: describeError(err) }));
    return () => {
      cancelled = true;
    };
  }, [api, applicantId, runId]);

  const current = result && result.runId === runId ? result : null;
  const run = current?.run ?? null;
  const error = current?.error ?? null;

  const json = run
    ? JSON.stringify(
        { details: run.details, error: run.error, output: run.output },
        null,
        2,
      )
    : "";

  return (
    <Modal
      opened={stage !== null}
      onClose={onClose}
      title={
        stage
          ? `${STAGES.find((s) => s.type === stage.agent_type)?.title} · ${stage.status}`
          : ""
      }
      size="xl"
      centered
    >
      {error && (
        <Text c="red" size="sm">
          {error}
        </Text>
      )}
      {!run && !error && (
        <Group justify="center" py="md">
          <Loader size="sm" />
        </Group>
      )}
      {run && (
        <Stack gap="xs">
          <Group justify="space-between">
            <Text size="xs" c="dimmed">
              {run.output === null
                ? "This stage produced no output."
                : `${json.length.toLocaleString()} characters`}
            </Text>
            <CopyButton value={json}>
              {({ copied, copy }) => (
                <Button size="compact-xs" variant="light" onClick={copy}>
                  {copied ? "Copied" : "Copy JSON"}
                </Button>
              )}
            </CopyButton>
          </Group>
          <ScrollArea.Autosize mah="65vh">
            <Code block style={{ fontSize: 12 }}>
              {json}
            </Code>
          </ScrollArea.Autosize>
        </Stack>
      )}
    </Modal>
  );
}

function duration(stage: ProcessingStage): string {
  const start = new Date(stage.started_at).getTime();
  const end = stage.completed_at ? new Date(stage.completed_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  const text = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return stage.completed_at ? text : `${text} so far`;
}
