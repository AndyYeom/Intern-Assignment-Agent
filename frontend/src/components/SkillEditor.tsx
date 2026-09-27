"use client";

import { useEffect, useState } from "react";
import {
  Accordion,
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Modal,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useApi } from "@/lib/api-context";
import { VerificationBadge } from "@/components/StatusBadge";
import { describeError } from "@/lib/format";
import { PROFICIENCY_LABELS } from "@/lib/types";
import type {
  ApplicantSkillOut,
  EvidenceOut,
  EvidenceSource,
  SkillOut,
} from "@/lib/types";

const LEVEL_OPTIONS = [
  { value: "1", label: "Entry" },
  { value: "2", label: "Intermediate" },
  { value: "3", label: "Advanced" },
];

const OBSERVED_OPTIONS = [
  { value: "", label: "Not observed" },
  ...LEVEL_OPTIONS,
];

const SOURCE_OPTIONS: { value: EvidenceSource; label: string }[] = [
  { value: "resume", label: "Resume" },
  { value: "portfolio", label: "Portfolio" },
  { value: "github", label: "GitHub" },
  { value: "manager", label: "Manager" },
];

export function SkillEditor({
  applicantId,
  skills,
  editable,
  onChanged,
}: {
  applicantId: string;
  skills: ApplicantSkillOut[];
  editable: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  return (
    <Stack gap="sm">
      <Text size="xs" c="dimmed">
        {editable
          ? "Edited skills are kept when the applicant is reprocessed."
          : "Skills can't be edited while the applicant is being processed."}
      </Text>

      {skills.length === 0 ? (
        <Text size="sm" c="dimmed">
          No skills recorded yet.
        </Text>
      ) : (
        <Accordion variant="separated" value={expanded} onChange={setExpanded}>
          {skills.map((skill) => (
            <SkillItem
              key={skill.skill_id}
              applicantId={applicantId}
              skill={skill}
              expanded={expanded === skill.skill_id}
              editable={editable}
              onChanged={onChanged}
            />
          ))}
        </Accordion>
      )}

      <Group justify="flex-start">
        <Button
          size="xs"
          variant="light"
          leftSection={<Plus size={14} />}
          disabled={!editable}
          onClick={() => setAdding(true)}
        >
          Add skill
        </Button>
      </Group>

      <AddSkillModal
        opened={adding}
        applicantId={applicantId}
        existingSkillIds={skills.map((s) => s.skill_id)}
        onClose={() => setAdding(false)}
        onChanged={onChanged}
      />
    </Stack>
  );
}

function SkillItem({
  applicantId,
  skill,
  expanded,
  editable,
  onChanged,
}: {
  applicantId: string;
  skill: ApplicantSkillOut;
  expanded: boolean;
  editable: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const api = useApi();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [savingObserved, setSavingObserved] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      await api.deleteSkill(applicantId, skill.skill_id);
      notifications.show({
        title: "Skill removed",
        message: `${skill.name} is now hidden from matching.`,
        color: "blue",
      });
      setConfirmDelete(false);
      await onChanged();
    } catch (err) {
      notifications.show({
        title: "Couldn't remove skill",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setDeleting(false);
    }
  }

  async function handleObservedChange(value: string | null) {
    setSavingObserved(true);
    try {
      await api.updateSkill(applicantId, skill.skill_id, {
        observed_level: value ? Number(value) : null,
      });
      await onChanged();
    } catch (err) {
      notifications.show({
        title: "Couldn't update observed level",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setSavingObserved(false);
    }
  }

  return (
    <Accordion.Item value={skill.skill_id}>
      <Group gap={0} wrap="nowrap" align="center">
        <Accordion.Control>
          <Group justify="space-between" wrap="wrap" pr="md">
            <Group gap="sm">
              <Text fw={500}>{skill.name}</Text>
              <Badge size="sm" variant="outline">
                {skill.category}
              </Badge>
              {skill.source === "manager" && (
                <Badge size="xs" variant="light" color="violet">
                  added by manager
                </Badge>
              )}
              {skill.edited_at && (
                <Badge size="xs" variant="light" color="gray">
                  edited
                </Badge>
              )}
            </Group>
            <Group gap="sm">
              <Text size="sm">
                Final:{" "}
                <b>
                  {PROFICIENCY_LABELS[skill.final_level] ?? skill.final_level}
                </b>
              </Text>
              <Text size="sm" c="dimmed">
                Claimed: {levelLabel(skill.claimed_level)} → Observed:{" "}
                {levelLabel(skill.observed_level)}
              </Text>
              <VerificationBadge status={skill.verification_status} />
            </Group>
          </Group>
        </Accordion.Control>
        {/* Outside the control: a button may not sit inside the control's button. */}
        <ActionIcon
          variant="subtle"
          color="red"
          mr="xs"
          disabled={!editable}
          aria-label={`Remove ${skill.name}`}
          onClick={() => setConfirmDelete(true)}
        >
          <Trash2 size={14} />
        </ActionIcon>
      </Group>
      <Accordion.Panel>
        <Stack gap={8}>
          <Group gap="xs">
            <Text size="sm" c="dimmed">
              Observed level
            </Text>
            {expanded ? (
              <Select
                size="xs"
                w={170}
                data={OBSERVED_OPTIONS}
                value={skill.observed_level ? String(skill.observed_level) : ""}
                onChange={handleObservedChange}
                disabled={!editable || savingObserved}
                allowDeselect={false}
              />
            ) : (
              <Text size="sm">{levelLabel(skill.observed_level)}</Text>
            )}
          </Group>

          <EditableText
            label="Claim"
            value={skill.claim_summary}
            editable={editable}
            onSave={(value) =>
              api
                .updateSkill(applicantId, skill.skill_id, {
                  claim_summary: value,
                })
                .then(() => onChanged())
            }
          />
          <EditableText
            label="Verification"
            value={skill.verification_summary}
            editable={editable}
            onSave={(value) =>
              api
                .updateSkill(applicantId, skill.skill_id, {
                  verification_summary: value,
                })
                .then(() => onChanged())
            }
          />

          <EvidenceSection
            applicantId={applicantId}
            skillId={skill.skill_id}
            evidence={skill.evidence}
            editable={editable}
            onChanged={onChanged}
          />
        </Stack>
      </Accordion.Panel>

      <Modal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Remove skill"
        centered
      >
        <Stack>
          <Text size="sm">
            Remove {skill.name}? It will be hidden from matching. You can
            restore it by adding the skill again.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button color="red" loading={deleting} onClick={handleDelete}>
              Remove
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Accordion.Item>
  );
}

function EditableText({
  label,
  value,
  editable,
  onSave,
}: {
  label: string;
  value: string | null;
  editable: boolean;
  onSave: (value: string | null) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [saving, setSaving] = useState(false);

  if (editing) {
    return (
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          {label}
        </Text>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.currentTarget.value)}
          autosize
          minRows={2}
          size="sm"
        />
        <Group gap="xs" justify="flex-end">
          <Button
            size="compact-xs"
            variant="default"
            onClick={() => setEditing(false)}
          >
            Cancel
          </Button>
          <Button
            size="compact-xs"
            loading={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave(draft.trim() ? draft.trim() : null);
                setEditing(false);
              } catch (err) {
                notifications.show({
                  title: `Couldn't update ${label.toLowerCase()}`,
                  message: describeError(err),
                  color: "red",
                });
              } finally {
                setSaving(false);
              }
            }}
          >
            Save
          </Button>
        </Group>
      </Stack>
    );
  }

  return (
    <Group gap={4} align="flex-start" wrap="nowrap">
      {value ? (
        <Text size="sm">
          <b>{label}: </b>
          {value}
        </Text>
      ) : (
        <Text size="sm" c="dimmed">
          No {label.toLowerCase()} recorded.
        </Text>
      )}
      {editable && (
        <ActionIcon
          size="sm"
          variant="subtle"
          aria-label={`Edit ${label.toLowerCase()}`}
          onClick={() => {
            setDraft(value ?? "");
            setEditing(true);
          }}
        >
          <Pencil size={12} />
        </ActionIcon>
      )}
    </Group>
  );
}

function EvidenceSection({
  applicantId,
  skillId,
  evidence,
  editable,
  onChanged,
}: {
  applicantId: string;
  skillId: string;
  evidence: EvidenceOut[];
  editable: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const [adding, setAdding] = useState(false);

  return (
    <>
      <Divider label="Evidence" labelPosition="left" />
      <Stack gap={6}>
        {evidence.length === 0 && (
          <Text size="xs" c="dimmed">
            No evidence recorded.
          </Text>
        )}
        {evidence.map((ev) => (
          <EvidenceCard
            key={ev.id}
            applicantId={applicantId}
            skillId={skillId}
            evidence={ev}
            editable={editable}
            onChanged={onChanged}
          />
        ))}
      </Stack>
      <Group justify="flex-start">
        <Button
          size="xs"
          variant="subtle"
          leftSection={<Plus size={14} />}
          disabled={!editable}
          onClick={() => setAdding(true)}
        >
          Add evidence
        </Button>
      </Group>

      <Modal
        opened={adding}
        onClose={() => setAdding(false)}
        title="Add evidence"
        centered
      >
        <EvidenceForm
          applicantId={applicantId}
          skillId={skillId}
          initial={{
            source_type: "manager",
            reference: null,
            excerpt: null,
            level: null,
          }}
          onCancel={() => setAdding(false)}
          onSaved={async () => {
            setAdding(false);
            await onChanged();
          }}
        />
      </Modal>
    </>
  );
}

function EvidenceCard({
  applicantId,
  skillId,
  evidence,
  editable,
  onChanged,
}: {
  applicantId: string;
  skillId: string;
  evidence: EvidenceOut;
  editable: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const api = useApi();
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      await api.deleteEvidence(applicantId, skillId, evidence.id);
      notifications.show({
        title: "Evidence removed",
        message: "The evidence entry was deleted.",
        color: "blue",
      });
      setConfirmDelete(false);
      await onChanged();
    } catch (err) {
      notifications.show({
        title: "Couldn't remove evidence",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setDeleting(false);
    }
  }

  if (editing) {
    return (
      <EvidenceForm
        applicantId={applicantId}
        skillId={skillId}
        evidenceId={evidence.id}
        initial={evidence}
        onCancel={() => setEditing(false)}
        onSaved={async () => {
          setEditing(false);
          await onChanged();
        }}
      />
    );
  }

  return (
    <Card withBorder padding="xs" radius="sm">
      <Group justify="space-between" mb={4}>
        <Group gap={6}>
          <Badge size="xs" variant="light">
            {evidence.source_type}
          </Badge>
          {evidence.edited_at && (
            <Badge size="xs" variant="light" color="gray">
              edited
            </Badge>
          )}
        </Group>
        <Group gap={4}>
          {evidence.level !== null && (
            <Text size="xs" c="dimmed">
              Level: {PROFICIENCY_LABELS[evidence.level] ?? evidence.level}
            </Text>
          )}
          <ActionIcon
            size="sm"
            variant="subtle"
            disabled={!editable}
            aria-label="Edit evidence"
            onClick={() => setEditing(true)}
          >
            <Pencil size={12} />
          </ActionIcon>
          <ActionIcon
            size="sm"
            variant="subtle"
            color="red"
            disabled={!editable}
            aria-label="Remove evidence"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 size={12} />
          </ActionIcon>
        </Group>
      </Group>
      {evidence.reference && (
        <Text size="xs" mb={2}>
          {isUrl(evidence.reference) ? (
            <Anchor href={evidence.reference} target="_blank" size="xs">
              {evidence.reference}
            </Anchor>
          ) : (
            evidence.reference
          )}
        </Text>
      )}
      {evidence.excerpt && (
        <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
          {evidence.excerpt}
        </Text>
      )}

      <Modal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Remove evidence"
        centered
      >
        <Stack>
          <Text size="sm">
            Remove this evidence entry? It is hidden from the profile but kept on record.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button color="red" loading={deleting} onClick={handleDelete}>
              Remove
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

function EvidenceForm({
  applicantId,
  skillId,
  evidenceId,
  initial,
  onCancel,
  onSaved,
}: {
  applicantId: string;
  skillId: string;
  evidenceId?: string;
  initial: {
    source_type: EvidenceSource;
    reference: string | null;
    excerpt: string | null;
    level: number | null;
  };
  onCancel: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const api = useApi();
  const [sourceType, setSourceType] = useState<EvidenceSource>(
    initial.source_type,
  );
  const [reference, setReference] = useState(initial.reference ?? "");
  const [excerpt, setExcerpt] = useState(initial.excerpt ?? "");
  const [level, setLevel] = useState<string | null>(
    initial.level ? String(initial.level) : "",
  );
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    setSaving(true);
    const body = {
      source_type: sourceType,
      reference: reference.trim() ? reference.trim() : null,
      excerpt: excerpt.trim() ? excerpt.trim() : null,
      level: level ? Number(level) : null,
    };
    try {
      if (evidenceId) {
        await api.updateEvidence(applicantId, skillId, evidenceId, body);
      } else {
        await api.addEvidence(applicantId, skillId, body);
      }
      notifications.show({
        title: evidenceId ? "Evidence updated" : "Evidence added",
        message: evidenceId
          ? "The evidence entry was updated."
          : "The evidence entry was added.",
        color: "blue",
      });
      await onSaved();
    } catch (err) {
      notifications.show({
        title: evidenceId
          ? "Couldn't update evidence"
          : "Couldn't add evidence",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card withBorder padding="xs" radius="sm">
      <Stack gap={6}>
        <Select
          label="Source"
          size="xs"
          data={SOURCE_OPTIONS}
          value={sourceType}
          onChange={(v) => v && setSourceType(v as EvidenceSource)}
          allowDeselect={false}
        />
        <TextInput
          label="Reference"
          size="xs"
          placeholder="URL or “page 2”"
          value={reference}
          onChange={(e) => setReference(e.currentTarget.value)}
        />
        <Textarea
          label="Excerpt"
          size="xs"
          autosize
          minRows={2}
          value={excerpt}
          onChange={(e) => setExcerpt(e.currentTarget.value)}
        />
        <Select
          label="Level"
          size="xs"
          data={[{ value: "", label: "None" }, ...LEVEL_OPTIONS]}
          value={level}
          onChange={setLevel}
          allowDeselect={false}
        />
        <Group gap="xs" justify="flex-end">
          <Button size="compact-xs" variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button size="compact-xs" loading={saving} onClick={handleSubmit}>
            Save
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

function AddSkillModal({
  opened,
  applicantId,
  existingSkillIds,
  onClose,
  onChanged,
}: {
  opened: boolean;
  applicantId: string;
  existingSkillIds: string[];
  onClose: () => void;
  onChanged: () => Promise<void> | void;
}) {
  const api = useApi();
  const [allSkills, setAllSkills] = useState<SkillOut[] | null>(null);
  const [skillId, setSkillId] = useState<string | null>(null);
  const [claimedLevel, setClaimedLevel] = useState<string | null>(null);
  const [observedLevel, setObservedLevel] = useState<string | null>("");
  const [claimSummary, setClaimSummary] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!opened) return;
    let cancelled = false;
    api
      .listSkills()
      .then((data) => !cancelled && setAllSkills(data))
      .catch(() => !cancelled && setAllSkills([]));
    return () => {
      cancelled = true;
    };
  }, [opened, api]);

  const loadingSkills = allSkills === null;

  const options = (allSkills ?? [])
    .filter((s) => !existingSkillIds.includes(s.id))
    .map((s) => ({ value: s.id, label: `${s.name} (${s.category})` }));

  function handleClose() {
    setSkillId(null);
    setClaimedLevel(null);
    setObservedLevel("");
    setClaimSummary("");
    onClose();
  }

  async function handleSubmit() {
    if (!skillId || !claimedLevel) return;
    setSaving(true);
    try {
      await api.addSkill(applicantId, {
        skill_id: skillId,
        claimed_level: Number(claimedLevel),
        observed_level: observedLevel ? Number(observedLevel) : null,
        claim_summary: claimSummary.trim() ? claimSummary.trim() : null,
      });
      notifications.show({
        title: "Skill added",
        message: "The skill was added to the applicant.",
        color: "blue",
      });
      handleClose();
      await onChanged();
    } catch (err) {
      notifications.show({
        title: "Couldn't add skill",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal opened={opened} onClose={handleClose} title="Add skill" centered>
      <Stack>
        <Select
          label="Skill"
          placeholder="Search skills"
          searchable
          data={options}
          value={skillId}
          onChange={setSkillId}
          disabled={loadingSkills}
          nothingFoundMessage="No matching skills"
          required
        />
        <Select
          label="Claimed level"
          data={LEVEL_OPTIONS}
          value={claimedLevel}
          onChange={setClaimedLevel}
          required
        />
        <Select
          label="Observed level"
          data={OBSERVED_OPTIONS}
          value={observedLevel}
          onChange={setObservedLevel}
          allowDeselect={false}
        />
        <Textarea
          label="Claim summary"
          placeholder="Optional"
          autosize
          minRows={2}
          value={claimSummary}
          onChange={(e) => setClaimSummary(e.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            loading={saving}
            disabled={!skillId || !claimedLevel}
            onClick={handleSubmit}
          >
            Add
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
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
