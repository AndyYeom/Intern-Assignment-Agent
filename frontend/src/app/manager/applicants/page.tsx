"use client";

import { useEffect, useState } from "react";
import {
  Anchor,
  Badge,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { useApi } from "@/lib/api-context";
import { ApplicantStatusBadge } from "@/components/StatusBadge";
import { ErrorAlert } from "@/components/ErrorAlert";
import { formatDateOnly } from "@/lib/format";
import type { ApplicantListItem } from "@/lib/types";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "submitted", label: "Submitted" },
  { value: "processing", label: "Processing" },
  { value: "ready", label: "Ready" },
  { value: "failed", label: "Failed" },
];

const PLACEMENT_OPTIONS = [
  { value: "", label: "Any placement" },
  { value: "assigned", label: "Assigned (approved)" },
  { value: "unassigned", label: "Not assigned" },
];

export default function ApplicantsPage() {
  const api = useApi();
  const router = useRouter();
  const [applicants, setApplicants] = useState<ApplicantListItem[] | null>(
    null,
  );
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string>("");
  const [placement, setPlacement] = useState<"" | "assigned" | "unassigned">("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const data = await api.listApplicants({
          status: status || undefined,
          q: query || undefined,
          placement: placement || undefined,
        });
        if (!cancelled) {
          setApplicants(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [api, status, query, placement]);

  // While any applicant is still being processed, refresh the list quietly.
  const inProgress = (applicants ?? []).some(
    (a) => a.status === "submitted" || a.status === "processing",
  );
  useEffect(() => {
    if (!inProgress) return;
    const timer = setInterval(async () => {
      try {
        setApplicants(
          await api.listApplicants({
            status: status || undefined,
            q: query || undefined,
            placement: placement || undefined,
          }),
        );
      } catch {
        // Keep the current rows; the next tick retries.
      }
    }, 10000);
    return () => clearInterval(timer);
  }, [inProgress, api, status, query, placement]);

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Title order={2}>Applicants</Title>
      </Group>

      <Group>
        <TextInput
          placeholder="Search by name or email"
          leftSection={<Search size={16} />}
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          w={320}
        />
        <Select
          data={STATUS_OPTIONS}
          value={status}
          onChange={(v) => setStatus(v ?? "")}
          w={200}
          allowDeselect={false}
        />
        <Select
          data={PLACEMENT_OPTIONS}
          value={placement}
          onChange={(v) => setPlacement((v ?? "") as typeof placement)}
          w={220}
          allowDeselect={false}
        />
      </Group>

      <ErrorAlert error={error} title="Couldn't load applicants" />

      {loading && !applicants && (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      )}

      {applicants && applicants.length === 0 && !loading && (
        <Text c="dimmed">No applicants match these filters.</Text>
      )}

      {applicants && applicants.length > 0 && (
        <Table.ScrollContainer minWidth={900}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Applicant</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Skills</Table.Th>
                <Table.Th>GitHub</Table.Th>
                <Table.Th>Submitted</Table.Th>
                <Table.Th>Assignment</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {applicants.map((a) => (
                <Table.Tr
                  key={a.id}
                  style={{ cursor: "pointer" }}
                  onClick={() => router.push(`/manager/applicants/${a.id}`)}
                >
                  <Table.Td>
                    <Stack gap={0}>
                      <Text fw={500}>{a.name}</Text>
                      <Text size="xs" c="dimmed">
                        {a.email}
                      </Text>
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      <ApplicantStatusBadge status={a.status} />
                      {a.assignment?.status === "approved" && (
                        <Badge size="sm" color="teal" variant="filled">
                          Assigned
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      <Text size="sm" c="dimmed">
                        {a.skill_count}
                      </Text>
                      {a.top_skills.slice(0, 3).map((s) => (
                        <Badge key={s.skill_id} size="sm" variant="outline">
                          {s.name}
                        </Badge>
                      ))}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {a.github_url ? (
                      <Anchor
                        href={a.github_url}
                        target="_blank"
                        size="sm"
                        onClick={(e) => e.stopPropagation()}
                      >
                        GitHub
                      </Anchor>
                    ) : (
                      <Text c="dimmed" size="sm">
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>{formatDateOnly(a.submitted_at)}</Table.Td>
                  <Table.Td>
                    {a.assignment && a.assignment.status !== "rejected" ? (
                      <Stack gap={0}>
                        <Text
                          size="sm"
                          c={a.assignment.status === "approved" ? undefined : "dimmed"}
                        >
                          {a.assignment.project_name} · {a.assignment.role_name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {a.assignment.status === "approved" ? "approved" : "proposed, not approved"}
                        </Text>
                      </Stack>
                    ) : (
                      <Text c="dimmed" size="sm">
                        —
                      </Text>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}
