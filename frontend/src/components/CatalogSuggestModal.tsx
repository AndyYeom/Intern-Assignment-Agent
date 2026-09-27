"use client";

import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Info, TriangleAlert } from "lucide-react";
import { useApi } from "@/lib/api-context";
import { describeError } from "@/lib/format";
import { ErrorAlert } from "@/components/ErrorAlert";
import type {
  ProjectOut,
  RequirementIn,
  RequirementSuggestion,
  RequirementType,
  SuggestedRequirement,
} from "@/lib/types";

interface SuggestionRow extends SuggestedRequirement {
  included: boolean;
}

const REQUIREMENT_TYPE_OPTIONS = [
  { value: "hard_requirement", label: "Hard requirement" },
  { value: "preferred", label: "Preferred" },
  { value: "learning_opportunity", label: "Learning opportunity" },
];

const LEVEL_OPTIONS = [
  { value: "1", label: "Entry" },
  { value: "2", label: "Intermediate" },
  { value: "3", label: "Advanced" },
];

/**
 * Presentational modal: the caller owns fetching the suggestion (triggered from a
 * click handler, not from an effect) and passes the current loading/result/error
 * state in. The editable form below is keyed on `version` so it re-initializes
 * from a fresh suggestion without needing to sync state in an effect.
 */
export function CatalogSuggestModal({
  project,
  loading,
  suggestion,
  error,
  version,
  onRetry,
  onClose,
  onCreated,
}: {
  project: ProjectOut;
  loading: boolean;
  suggestion: RequirementSuggestion | null;
  error: unknown;
  version: number;
  onRetry: () => void;
  onClose: () => void;
  onCreated: () => void;
}) {
  return (
    <Modal
      opened
      onClose={onClose}
      title={`Catalog agent suggestion — ${project.name}`}
      size="xl"
    >
      <Stack gap="sm">
        {loading && (
          <Group justify="center" py="xl" gap="sm">
            <Loader />
            <Text size="sm" c="dimmed">
              Reading the project description… this takes about 30–60
              seconds.
            </Text>
          </Group>
        )}

        {!loading && Boolean(error) && (
          <Stack gap="sm">
            <ErrorAlert error={error} title="Couldn't get suggestions" />
            <Group justify="flex-end">
              <Button variant="subtle" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={onRetry}>Try again</Button>
            </Group>
          </Stack>
        )}

        {!loading && !error && suggestion && (
          <SuggestionForm
            key={version}
            project={project}
            suggestion={suggestion}
            onRetry={onRetry}
            onClose={onClose}
            onCreated={onCreated}
          />
        )}
      </Stack>
    </Modal>
  );
}

function SuggestionForm({
  project,
  suggestion,
  onRetry,
  onClose,
  onCreated,
}: {
  project: ProjectOut;
  suggestion: RequirementSuggestion;
  onRetry: () => void;
  onClose: () => void;
  onCreated: () => void;
}) {
  const api = useApi();
  const [rows, setRows] = useState<SuggestionRow[]>(() =>
    suggestion.requirements.map((r) => ({ ...r, included: true })),
  );
  const [roleName, setRoleName] = useState(`${project.name} developer`);
  const [roleDescription, setRoleDescription] = useState("");
  const [capacity, setCapacity] = useState<number>(1);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);

  function updateRow(index: number, patch: Partial<SuggestionRow>) {
    setRows((prev) =>
      prev.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    );
  }

  const includedCount = rows.filter((r) => r.included).length;
  const canCreate =
    roleName.trim().length > 0 && capacity >= 1 && includedCount > 0;

  async function handleCreate() {
    if (!canCreate) return;
    setCreating(true);
    setCreateError(null);
    try {
      const requirements: RequirementIn[] = rows
        .filter((r) => r.included)
        .map((r) => ({
          skill_id: r.skill_id,
          required_level: r.required_level,
          requirement_type: r.requirement_type,
          weight: r.weight,
        }));
      await api.createRole(project.id, {
        name: roleName,
        description: roleDescription,
        capacity,
        requirements,
      });
      notifications.show({
        title: "Role created",
        message: roleName,
        color: "green",
      });
      onCreated();
    } catch (err) {
      setCreateError(err);
      notifications.show({
        title: "Couldn't create role",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" style={{ flex: 1 }}>
          {suggestion.summary}
        </Text>
        <Badge variant="light">{suggestion.provider}</Badge>
      </Group>

      {suggestion.unresolved.length > 0 && (
        <Alert color="yellow" title="Some skills weren't matched">
          <Stack gap={4}>
            <Text size="sm">
              The agent couldn&apos;t map these to the skill catalog — add
              them manually if needed.
            </Text>
            {suggestion.unresolved.map((u, i) => (
              <Text key={i} size="sm">
                &bull; {u.raw_skill} (
                {REQUIREMENT_TYPE_OPTIONS.find(
                  (o) => o.value === u.requirement_type,
                )?.label ?? u.requirement_type}
                )
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {(suggestion.uncertainties.length > 0 ||
        suggestion.issues.length > 0) && (
        <Stack gap={2}>
          {suggestion.uncertainties.map((u, i) => (
            <Text key={`u-${i}`} size="xs" c="dimmed">
              &bull; {u}
            </Text>
          ))}
          {suggestion.issues.map((iss, i) => (
            <Text key={`i-${i}`} size="xs" c="dimmed">
              &bull; {iss}
            </Text>
          ))}
        </Stack>
      )}

      {rows.length === 0 ? (
        <Text size="sm" c="dimmed">
          The agent didn&apos;t suggest any requirements.
        </Text>
      ) : (
        <Table verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              <Table.Th>Skill</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Level</Table.Th>
              <Table.Th>Weight</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row, index) => (
              <Table.Tr key={row.skill_id}>
                <Table.Td>
                  <Checkbox
                    checked={row.included}
                    onChange={(e) =>
                      updateRow(index, {
                        included: e.currentTarget.checked,
                      })
                    }
                  />
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{row.skill_name}</Text>
                  <Text size="xs" c="dimmed">
                    {row.skill_id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Select
                    data={REQUIREMENT_TYPE_OPTIONS}
                    value={row.requirement_type}
                    onChange={(v) =>
                      updateRow(index, {
                        requirement_type:
                          (v as RequirementType) ?? row.requirement_type,
                      })
                    }
                    allowDeselect={false}
                    w={180}
                  />
                </Table.Td>
                <Table.Td>
                  <Stack gap={2}>
                    <Select
                      data={LEVEL_OPTIONS}
                      value={String(row.required_level)}
                      onChange={(v) =>
                        updateRow(index, {
                          required_level: Number(v ?? row.required_level),
                        })
                      }
                      allowDeselect={false}
                      w={140}
                    />
                    {!row.level_suggested && (
                      <Text size="xs" c="orange">
                        level not specified — please confirm
                      </Text>
                    )}
                  </Stack>
                </Table.Td>
                <Table.Td>
                  <NumberInput
                    value={row.weight}
                    onChange={(v) =>
                      updateRow(index, { weight: Number(v) || 0.1 })
                    }
                    min={0.1}
                    max={5}
                    step={0.5}
                    w={90}
                  />
                </Table.Td>
                <Table.Td>
                  <Tooltip
                    multiline
                    w={300}
                    label={
                      <Stack gap={4}>
                        <Text size="xs">{row.evidence_text}</Text>
                        <Text size="xs" c="dimmed">
                          {row.decision_basis}
                        </Text>
                      </Stack>
                    }
                  >
                    <Info size={16} />
                  </Tooltip>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Stack gap="sm" mt="sm">
        <Text size="sm" fw={500}>
          Role details
        </Text>
        <ErrorAlert error={createError} />
        <TextInput
          label="Role name"
          value={roleName}
          onChange={(e) => setRoleName(e.currentTarget.value)}
          required
        />
        <NumberInput
          label="Capacity"
          description="The agent never guesses capacity; set how many interns this role takes."
          min={1}
          value={capacity}
          onChange={(v) => setCapacity(Number(v) || 1)}
          required
        />
        <Textarea
          label="Description (optional)"
          value={roleDescription}
          onChange={(e) => setRoleDescription(e.currentTarget.value)}
          minRows={2}
        />
      </Stack>

      <Group gap={6} justify="flex-start">
        <TriangleAlert size={14} />
        <Text size="xs" c="dimmed">
          Nothing is saved until you click &quot;Create role&quot;.
        </Text>
      </Group>

      <Group justify="flex-end" mt="sm">
        <Button variant="subtle" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="light" onClick={onRetry}>
          Try again
        </Button>
        <Button onClick={handleCreate} loading={creating} disabled={!canCreate}>
          Create role
        </Button>
      </Group>
    </>
  );
}
