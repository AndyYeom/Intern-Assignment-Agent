"use client";

import { use, useCallback, useEffect, useState } from "react";
import {
  Accordion,
  Anchor,
  Badge,
  Button,
  Card,
  Divider,
  Grid,
  Group,
  Loader,
  Progress,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { RefreshCw } from "lucide-react";
import { useApi } from "@/lib/api-context";
import { ApplicantStatusBadge, VerificationBadge } from "@/components/StatusBadge";
import { ErrorAlert } from "@/components/ErrorAlert";
import { describeError, formatDate } from "@/lib/format";
import { PROFICIENCY_LABELS } from "@/lib/types";
import type { ApplicantDetail } from "@/lib/types";

export default function ApplicantDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const api = useApi();
  const [applicant, setApplicant] = useState<ApplicantDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [reprocessing, setReprocessing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.getApplicant(id);
      setApplicant(data);
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

  // Processing runs on the server for a few minutes; refresh until it settles.
  const inProgress =
    applicant?.status === "submitted" || applicant?.status === "processing";
  useEffect(() => {
    if (!inProgress) return;
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [inProgress, load]);

  async function handleReprocess() {
    setReprocessing(true);
    try {
      await api.reprocessApplicant(id);
      notifications.show({
        title: "Reprocessing started",
        message: "The applicant is being reprocessed.",
        color: "blue",
      });
      await load();
    } catch (err) {
      notifications.show({
        title: "Couldn't reprocess",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setReprocessing(false);
    }
  }

  if (loading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  if (error) {
    return <ErrorAlert error={error} title="Couldn't load applicant" />;
  }

  if (!applicant) return null;

  const profile = applicant.profile ?? {};
  const education = asArray(profile.education);
  const workExperience = asArray(profile.work_experience ?? profile.experience);

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={2}>{applicant.name}</Title>
          <Text c="dimmed">{applicant.email}</Text>
        </Stack>
        <Group>
          <ApplicantStatusBadge status={applicant.status} />
          {applicant.status === "failed" && (
            <Button
              size="sm"
              variant="light"
              leftSection={<RefreshCw size={14} />}
              loading={reprocessing}
              onClick={handleReprocess}
            >
              Reprocess
            </Button>
          )}
        </Group>
      </Group>

      <Grid>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder radius="md" p="md" h="100%">
            <Title order={4} mb="sm">
              Details
            </Title>
            <Stack gap={6}>
              <DetailRow label="Reference">{applicant.reference}</DetailRow>
              <DetailRow label="Submitted">
                {formatDate(applicant.submitted_at)}
              </DetailRow>
              <DetailRow label="Processed">
                {formatDate(applicant.processed_at)}
              </DetailRow>
              <DetailRow label="GitHub">
                {applicant.github_url ? (
                  <Anchor href={applicant.github_url} target="_blank" size="sm">
                    {applicant.github_login ?? applicant.github_url}
                  </Anchor>
                ) : (
                  "—"
                )}
              </DetailRow>
              <DetailRow label="Portfolio">
                {applicant.portfolio_url ? (
                  <Anchor href={applicant.portfolio_url} target="_blank" size="sm">
                    {applicant.portfolio_url}
                  </Anchor>
                ) : (
                  "—"
                )}
              </DetailRow>
              <DetailRow label="Documents">
                {applicant.documents.length === 0 && "—"}
                <Stack gap={4}>
                  {applicant.documents.map((d) => (
                    <Anchor
                      key={d.id}
                      href={api.downloadUrl(d.download_path)}
                      target="_blank"
                      size="sm"
                    >
                      {d.original_filename} ({d.document_type})
                    </Anchor>
                  ))}
                </Stack>
              </DetailRow>
            </Stack>
          </Card>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder radius="md" p="md" h="100%">
            <Title order={4} mb="sm">
              Processing
            </Title>
            {applicant.status_detail && (
              <Text size="sm" c={applicant.status === "failed" ? "red" : "dimmed"} mb="sm">
                {applicant.status_detail}
              </Text>
            )}
            <Stack gap={8}>
              {applicant.stages.length === 0 && (
                <Text size="sm" c="dimmed">
                  No processing stages recorded yet.
                </Text>
              )}
              {applicant.stages.map((s, i) => (
                <Group key={i} justify="space-between">
                  <Text size="sm" tt="capitalize">
                    {s.agent_type}
                  </Text>
                  <Group gap={8}>
                    <Badge
                      size="sm"
                      color={stageColor(s.status)}
                      variant="light"
                    >
                      {s.status}
                    </Badge>
                    {s.message && (
                      <Tooltip label={s.message}>
                        <Text size="xs" c="dimmed" style={{ maxWidth: 160 }} truncate>
                          {s.message}
                        </Text>
                      </Tooltip>
                    )}
                  </Group>
                </Group>
              ))}
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>

      <Card withBorder radius="md" p="md">
        <Title order={4} mb="sm">
          Current assignment
        </Title>
        {applicant.assignment ? (
          <Text size="sm">
            {applicant.assignment.project_name} · {applicant.assignment.role_name}{" "}
            — score {applicant.assignment.score.toFixed(1)}
          </Text>
        ) : (
          <Text size="sm" c="dimmed">
            Not currently assigned.
          </Text>
        )}
      </Card>

      <Card withBorder radius="md" p="md">
        <Title order={4} mb="sm">
          Skills
        </Title>
        {applicant.skills.length === 0 ? (
          <Text size="sm" c="dimmed">
            No skills recorded yet.
          </Text>
        ) : (
          <Accordion variant="separated">
            {applicant.skills.map((skill) => (
              <Accordion.Item key={skill.skill_id} value={skill.skill_id}>
                <Accordion.Control>
                  <Group justify="space-between" wrap="wrap" pr="md">
                    <Group gap="sm">
                      <Text fw={500}>{skill.name}</Text>
                      <Badge size="sm" variant="outline">
                        {skill.category}
                      </Badge>
                    </Group>
                    <Group gap="sm">
                      <Text size="sm">
                        Final:{" "}
                        <b>{PROFICIENCY_LABELS[skill.final_level] ?? skill.final_level}</b>
                      </Text>
                      <Text size="sm" c="dimmed">
                        Claimed: {levelLabel(skill.claimed_level)} → Observed:{" "}
                        {levelLabel(skill.observed_level)}
                      </Text>
                      <VerificationBadge status={skill.verification_status} />
                    </Group>
                  </Group>
                </Accordion.Control>
                <Accordion.Panel>
                  <Stack gap={8}>
                    {skill.claim_summary && (
                      <Text size="sm">
                        <b>Claim: </b>
                        {skill.claim_summary}
                      </Text>
                    )}
                    {skill.verification_summary && (
                      <Text size="sm">
                        <b>Verification: </b>
                        {skill.verification_summary}
                      </Text>
                    )}
                    {skill.evidence.length > 0 && (
                      <>
                        <Divider label="Evidence" labelPosition="left" />
                        <Stack gap={6}>
                          {skill.evidence.map((ev, idx) => (
                            <Card key={idx} withBorder padding="xs" radius="sm">
                              <Group justify="space-between" mb={4}>
                                <Badge size="xs" variant="light">
                                  {ev.source_type}
                                </Badge>
                                {ev.level !== null && (
                                  <Text size="xs" c="dimmed">
                                    Level: {PROFICIENCY_LABELS[ev.level] ?? ev.level}
                                  </Text>
                                )}
                              </Group>
                              {ev.reference && (
                                <Text size="xs" mb={2}>
                                  {isUrl(ev.reference) ? (
                                    <Anchor href={ev.reference} target="_blank" size="xs">
                                      {ev.reference}
                                    </Anchor>
                                  ) : (
                                    ev.reference
                                  )}
                                </Text>
                              )}
                              {ev.excerpt && (
                                <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
                                  {ev.excerpt}
                                </Text>
                              )}
                            </Card>
                          ))}
                        </Stack>
                      </>
                    )}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
        )}
      </Card>

      {(education.length > 0 || workExperience.length > 0) && (
        <Card withBorder radius="md" p="md">
          <Title order={4} mb="sm">
            Profile
          </Title>
          <Grid>
            {education.length > 0 && (
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Text fw={500} size="sm" mb={4}>
                  Education
                </Text>
                <Stack gap={4}>
                  {education.map((item, i) => (
                    <Text size="sm" key={i} c="dimmed">
                      {describeEntry(item)}
                    </Text>
                  ))}
                </Stack>
              </Grid.Col>
            )}
            {workExperience.length > 0 && (
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Text fw={500} size="sm" mb={4}>
                  Work experience
                </Text>
                <Stack gap={4}>
                  {workExperience.map((item, i) => (
                    <Text size="sm" key={i} c="dimmed">
                      {describeEntry(item)}
                    </Text>
                  ))}
                </Stack>
              </Grid.Col>
            )}
          </Grid>
        </Card>
      )}

      <Card withBorder radius="md" p="md">
        <Title order={4} mb="sm">
          Compatibility scores
        </Title>
        {applicant.scores.length === 0 ? (
          <Text size="sm" c="dimmed">
            No scores available yet. Scores appear after an assignment run
            includes this applicant.
          </Text>
        ) : (
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Project</Table.Th>
                <Table.Th>Role</Table.Th>
                <Table.Th>Fit</Table.Th>
                <Table.Th>Growth</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {[...applicant.scores]
                .sort((a, b) => b.fit_score - a.fit_score)
                .map((s, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>{s.project_name}</Table.Td>
                    <Table.Td>
                      <Group gap={6}>
                        {s.role_name}
                        {s.candidate && (
                          <Badge size="xs" variant="light" color="blue">
                            candidate
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td w={160}>
                      <Group gap={6}>
                        <Progress
                          value={s.fit_score}
                          w={80}
                          size="sm"
                          color="blue"
                        />
                        <Text size="xs">{s.fit_score.toFixed(0)}</Text>
                      </Group>
                    </Table.Td>
                    <Table.Td w={160}>
                      <Group gap={6}>
                        <Progress
                          value={s.growth_score}
                          w={80}
                          size="sm"
                          color="teal"
                        />
                        <Text size="xs">{s.growth_score.toFixed(0)}</Text>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
            </Table.Tbody>
          </Table>
        )}
      </Card>
    </Stack>
  );
}

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Group align="flex-start" gap="xs">
      <Text size="sm" c="dimmed" w={110}>
        {label}
      </Text>
      <div style={{ flex: 1 }}>
        {typeof children === "string" || typeof children === "number" ? (
          <Text size="sm">{children}</Text>
        ) : (
          children
        )}
      </div>
    </Group>
  );
}

function stageColor(status: string): string {
  switch (status) {
    case "succeeded":
      return "green";
    case "running":
      return "yellow";
    case "failed":
      return "red";
    default:
      return "gray";
  }
}

function levelLabel(level: number | null): string {
  if (level === null) return "—";
  return PROFICIENCY_LABELS[level] ?? String(level);
}

function isUrl(value: string): boolean {
  try {
    new URL(value);
    return true;
  } catch {
    return false;
  }
}

function asArray(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) {
    return value.filter((v): v is Record<string, unknown> => typeof v === "object" && v !== null);
  }
  return [];
}

function describeEntry(entry: Record<string, unknown>): string {
  const parts = [
    entry.degree,
    entry.institution ?? entry.school,
    entry.title ?? entry.role,
    entry.company ?? entry.organization,
    entry.field,
    entry.duration ?? entry.dates,
  ].filter((p) => typeof p === "string" && p.length > 0);
  if (parts.length > 0) return parts.join(" · ");
  return JSON.stringify(entry);
}
