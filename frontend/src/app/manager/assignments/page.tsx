"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Group, Loader, Stack, Table, Text, Title } from "@mantine/core";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { notifications } from "@mantine/notifications";
import { useApi } from "@/lib/api-context";
import { ErrorAlert } from "@/components/ErrorAlert";
import { RunStatusBadge } from "@/components/StatusBadge";
import { describeError, formatDate, formatScore } from "@/lib/format";
import type { RunSummary } from "@/lib/types";

export default function AssignmentsPage() {
  const api = useApi();
  const router = useRouter();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.listRuns();
      setRuns(data);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate() {
    setCreating(true);
    try {
      const run = await api.createRun({});
      notifications.show({
        title: "Assignment run started",
        message: "Using all active projects and ready applicants.",
        color: "blue",
      });
      router.push(`/manager/assignments/${run.id}`);
    } catch (err) {
      notifications.show({
        title: "Couldn't start run",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setCreating(false);
    }
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Title order={2}>Assignments</Title>
        <Button
          leftSection={<Plus size={16} />}
          onClick={handleCreate}
          loading={creating}
        >
          New assignment run
        </Button>
      </Group>

      <ErrorAlert error={error} title="Couldn't load assignment runs" />

      {loading && !runs && (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      )}

      {runs && runs.length === 0 && !loading && (
        <Text c="dimmed">No assignment runs yet.</Text>
      )}

      {runs && runs.length > 0 && (
        <Table highlightOnHover verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Status</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th>Final score</Table.Th>
              <Table.Th>Assigned</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {runs.map((run) => (
              <Table.Tr
                key={run.id}
                style={{ cursor: "pointer" }}
                onClick={() => router.push(`/manager/assignments/${run.id}`)}
              >
                <Table.Td>
                  <RunStatusBadge status={run.status} />
                </Table.Td>
                <Table.Td>{formatDate(run.created_at)}</Table.Td>
                <Table.Td>{formatScore(run.final_score)}</Table.Td>
                <Table.Td>
                  {run.assigned_count} / {run.applicant_count} applicants,{" "}
                  {run.role_count} roles
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
