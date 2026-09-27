"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Popover,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useApi } from "@/lib/api-context";
import { ErrorAlert } from "@/components/ErrorAlert";
import { AssignmentStatusBadge, RunStatusBadge } from "@/components/StatusBadge";
import { describeError, formatDate, formatScore } from "@/lib/format";
import type { AssignmentOut, RunDetail } from "@/lib/types";

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const api = useApi();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.getRun(id);
      setRun(data);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [api, id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!run) return;
    if (run.status !== "queued" && run.status !== "running") return;
    pollTimer.current = setTimeout(load, 3000);
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [run, load]);

  const roleOptions = (run?.utilization ?? []).flatMap((p) =>
    p.roles.map((r) => ({
      value: r.role_id,
      label: `${p.project_name} · ${r.role_name}`,
    })),
  );

  async function patchAssignment(
    assignment: AssignmentOut,
    body: Parameters<typeof api.patchAssignment>[1],
  ) {
    setBusyId(assignment.id);
    try {
      await api.patchAssignment(assignment.id, body);
      notifications.show({
        title: "Assignment updated",
        message: assignment.applicant.name,
        color: "green",
      });
      await load();
    } catch (err) {
      notifications.show({
        title: "Couldn't update assignment",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setBusyId(null);
    }
  }

  if (loading && !run) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  if (error) {
    return <ErrorAlert error={error} title="Couldn't load assignment run" />;
  }

  if (!run) return null;

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={2}>Assignment run</Title>
          <Text c="dimmed" size="sm">
            Created {formatDate(run.created_at)}
          </Text>
        </Stack>
        <Group>
          <RunStatusBadge status={run.status} />
          {(run.status === "queued" || run.status === "running") && (
            <Loader size="xs" />
          )}
        </Group>
      </Group>

      {run.status === "failed" && run.error && (
        <ErrorAlert error={new Error(run.error)} title="Run failed" />
      )}

      <Card withBorder radius="md" p="md">
        <Title order={4} mb="sm">
          Summary
        </Title>
        <Group gap="xl">
          <Stat label="Final score" value={formatScore(run.final_score)} />
          <Stat label="Applicants" value={String(run.applicant_count)} />
          <Stat label="Roles" value={String(run.role_count)} />
          <Stat label="Assigned" value={String(run.assigned_count)} />
        </Group>
        {run.score_breakdown && Object.keys(run.score_breakdown).length > 0 && (
          <Group gap="xl" mt="sm">
            {Object.entries(run.score_breakdown).map(([key, value]) => (
              <Stat key={key} label={key} value={value.toFixed(1)} />
            ))}
          </Group>
        )}
      </Card>

      <Card withBorder radius="md" p="md">
        <Title order={4} mb="sm">
          Capacity utilization
        </Title>
        <Stack gap="md">
          {run.utilization.map((p) => (
            <div key={p.project_id}>
              <Group justify="space-between" mb={4}>
                <Text fw={500} size="sm">
                  {p.project_name}
                </Text>
                <Text size="xs" c="dimmed">
                  {p.filled} / {p.capacity}
                </Text>
              </Group>
              <Stack gap={6}>
                {p.roles.map((r) => (
                  <Group key={r.role_id} gap="sm" wrap="nowrap">
                    <Text size="xs" w={160} truncate>
                      {r.role_name}
                    </Text>
                    <Progress
                      value={r.capacity > 0 ? (r.filled / r.capacity) * 100 : 0}
                      style={{ flex: 1 }}
                      size="sm"
                    />
                    <Text size="xs" w={50} ta="right">
                      {r.filled}/{r.capacity}
                    </Text>
                  </Group>
                ))}
              </Stack>
            </div>
          ))}
        </Stack>
      </Card>

      <Card withBorder radius="md" p="md">
        <Title order={4} mb="sm">
          Assignments
        </Title>
        {run.assignments.length === 0 ? (
          <Text size="sm" c="dimmed">
            No assignments yet.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={900}>
            <Table verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Applicant</Table.Th>
                  <Table.Th>Project</Table.Th>
                  <Table.Th>Role</Table.Th>
                  <Table.Th>Score</Table.Th>
                  <Table.Th>Reason</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Actions</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {run.assignments.map((a) => (
                  <Table.Tr key={a.id}>
                    <Table.Td>{a.applicant.name}</Table.Td>
                    <Table.Td>{a.project.name}</Table.Td>
                    <Table.Td>
                      <Stack gap={2}>
                        <Text size="sm">{a.role.name}</Text>
                        {a.overridden && (
                          <Group gap={4}>
                            <Badge size="xs" color="orange" variant="light">
                              overridden
                            </Badge>
                            <Text size="xs" c="dimmed">
                              was {a.solver_role.name}
                            </Text>
                          </Group>
                        )}
                      </Stack>
                    </Table.Td>
                    <Table.Td>{formatScore(a.score)}</Table.Td>
                    <Table.Td maw={260}>
                      <ReasonPopover assignment={a} />
                    </Table.Td>
                    <Table.Td>
                      <AssignmentStatusBadge status={a.status} />
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <Button
                          size="xs"
                          variant="light"
                          color="green"
                          disabled={a.status === "approved"}
                          loading={busyId === a.id}
                          onClick={() =>
                            patchAssignment(a, { status: "approved" })
                          }
                        >
                          Approve
                        </Button>
                        <Button
                          size="xs"
                          variant="light"
                          color="red"
                          disabled={a.status === "rejected"}
                          loading={busyId === a.id}
                          onClick={() =>
                            patchAssignment(a, { status: "rejected" })
                          }
                        >
                          Reject
                        </Button>
                        <Select
                          placeholder="Change role"
                          size="xs"
                          data={roleOptions}
                          value={null}
                          onChange={(v) => {
                            if (v) patchAssignment(a, { role_id: v });
                          }}
                          w={140}
                          searchable
                        />
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>

      <Card withBorder radius="md" p="md">
        <Title order={4} mb="sm">
          Unassigned applicants
        </Title>
        {run.unassigned.length === 0 ? (
          <Text size="sm" c="dimmed">
            Every applicant in this run received an assignment.
          </Text>
        ) : (
          <Stack gap={6}>
            {run.unassigned.map((u) => (
              <Group key={u.id} justify="space-between">
                <Text size="sm">{u.name}</Text>
                <Text size="xs" c="dimmed">
                  {u.candidate_role_count} candidate role
                  {u.candidate_role_count === 1 ? "" : "s"}
                </Text>
              </Group>
            ))}
          </Stack>
        )}
      </Card>
    </Stack>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed" tt="capitalize">
        {label}
      </Text>
      <Text fw={600}>{value}</Text>
    </Stack>
  );
}

function ReasonPopover({ assignment }: { assignment: AssignmentOut }) {
  const { reason } = assignment;
  return (
    <Popover width={300} position="left" withArrow shadow="md">
      <Popover.Target>
        <Text size="sm" lineClamp={1} style={{ cursor: "pointer" }} td="underline dotted">
          {reason.summary}
        </Text>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap={6}>
          <ReasonList label="Met" items={reason.met} color="green" />
          <ReasonList label="Below" items={reason.below} color="red" />
          <ReasonList label="Growth" items={reason.growth} color="blue" />
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

function ReasonList({
  label,
  items,
  color,
}: {
  label: string;
  items: string[];
  color: string;
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <Text size="xs" fw={600} c={color}>
        {label}
      </Text>
      {items.map((item, i) => (
        <Text size="xs" key={i}>
          {item}
        </Text>
      ))}
    </div>
  );
}
