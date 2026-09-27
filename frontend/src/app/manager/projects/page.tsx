"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  NumberInput,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/api-context";
import { CatalogSuggestModal } from "@/components/CatalogSuggestModal";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ProjectStatusBadge } from "@/components/StatusBadge";
import { describeError } from "@/lib/format";
import { REQUIREMENT_TYPE_LABELS } from "@/lib/types";
import type {
  ProjectOut,
  ProjectStatus,
  RequirementIn,
  RequirementSuggestion,
  RoleOut,
  SkillOut,
} from "@/lib/types";

export default function ProjectsPage() {
  const api = useApi();
  const [projects, setProjects] = useState<ProjectOut[] | null>(null);
  const [skills, setSkills] = useState<SkillOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectOut | null>(null);
  const [roleModalState, setRoleModalState] = useState<{
    project: ProjectOut;
    role: RoleOut | null;
  } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProjectOut | null>(null);
  const [suggestState, setSuggestState] = useState<{
    project: ProjectOut;
    loading: boolean;
    result: RequirementSuggestion | null;
    error: unknown;
    version: number;
  } | null>(null);

  const load = useCallback(async () => {
    try {
      const [projectData, skillData] = await Promise.all([
        api.listProjects(),
        api.listSkills(),
      ]);
      setProjects(projectData);
      setSkills(skillData);
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

  function handleSuggest(project: ProjectOut) {
    const version = (suggestState?.version ?? 0) + 1;
    setSuggestState({ project, loading: true, result: null, error: null, version });
    api
      .suggestRequirements(project.id)
      .then((result) => {
        setSuggestState({ project, loading: false, result, error: null, version });
      })
      .catch((err) => {
        setSuggestState({ project, loading: false, result: null, error: err, version });
      });
  }

  async function handleDeleteRole(role: RoleOut) {
    if (!confirm(`Delete role "${role.name}"?`)) return;
    try {
      await api.deleteRole(role.id);
      notifications.show({
        title: "Role deleted",
        message: `${role.name} was deleted.`,
        color: "green",
      });
      load();
    } catch (err) {
      notifications.show({
        title: "Couldn't delete role",
        message: describeError(err),
        color: "red",
      });
    }
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Title order={2}>Projects</Title>
        <Button
          leftSection={<Plus size={16} />}
          onClick={() => setProjectModalOpen(true)}
        >
          New project
        </Button>
      </Group>

      <ErrorAlert error={error} title="Couldn't load projects" />

      {loading && !projects && (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      )}

      {projects && projects.length === 0 && !loading && (
        <Text c="dimmed">No projects yet. Create one to get started.</Text>
      )}

      <Stack gap="md">
        {projects?.map((project) => (
          <Card key={project.id} withBorder radius="md" p="md">
            <Group justify="space-between" align="flex-start" mb="xs">
              <Stack gap={2}>
                <Group gap="sm">
                  <Title order={4}>{project.name}</Title>
                  <ProjectStatusBadge status={project.status} />
                </Group>
                {project.description && (
                  <Text size="sm" c="dimmed">
                    {project.description}
                  </Text>
                )}
                <Text size="xs" c="dimmed">
                  Total capacity: {project.capacity}
                </Text>
              </Stack>
              <Group>
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<Pencil size={14} />}
                  onClick={() => setEditingProject(project)}
                >
                  Edit project
                </Button>
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<Plus size={14} />}
                  onClick={() =>
                    setRoleModalState({ project, role: null })
                  }
                >
                  Add role
                </Button>
                {project.roles.length > 0 && (
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<Sparkles size={14} />}
                    onClick={() => handleSuggest(project)}
                  >
                    Suggest with catalog agent
                  </Button>
                )}
                <Button
                  size="xs"
                  variant="light"
                  color="red"
                  leftSection={<Trash2 size={14} />}
                  onClick={() => setDeleteTarget(project)}
                >
                  Delete project
                </Button>
              </Group>
            </Group>

            <Stack gap={8} mt="sm">
              {project.roles.length === 0 && (
                <Group justify="space-between" align="center">
                  <Text size="sm" c="dimmed">
                    No roles defined yet.
                  </Text>
                  <Button
                    size="xs"
                    leftSection={<Sparkles size={14} />}
                    onClick={() => handleSuggest(project)}
                  >
                    Suggest with catalog agent
                  </Button>
                </Group>
              )}
              {project.roles.map((role) => (
                <Card key={role.id} withBorder padding="sm" radius="sm">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={4}>
                      <Group gap="sm">
                        <Text fw={500}>{role.name}</Text>
                        <Text size="xs" c="dimmed">
                          Capacity: {role.capacity}
                        </Text>
                      </Group>
                      {role.description && (
                        <Text size="xs" c="dimmed">
                          {role.description}
                        </Text>
                      )}
                      <Group gap={6}>
                        {role.requirements.map((r) => (
                          <Badge key={r.skill_id} size="sm" variant="outline">
                            {r.skill_name} · {levelLabel(r.required_level)} ·{" "}
                            {REQUIREMENT_TYPE_LABELS[r.requirement_type]}
                          </Badge>
                        ))}
                      </Group>
                    </Stack>
                    <Group gap={4}>
                      <Tooltip label="Edit role">
                        <ActionIcon
                          variant="subtle"
                          onClick={() =>
                            setRoleModalState({ project, role })
                          }
                        >
                          <Pencil size={16} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Delete role">
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          onClick={() => handleDeleteRole(role)}
                        >
                          <Trash2 size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                </Card>
              ))}
            </Stack>
          </Card>
        ))}
      </Stack>

      {projectModalOpen && (
        <ProjectModal
          onClose={() => setProjectModalOpen(false)}
          onSaved={() => {
            setProjectModalOpen(false);
            load();
          }}
        />
      )}

      {editingProject && (
        <ProjectModal
          project={editingProject}
          onClose={() => setEditingProject(null)}
          onSaved={() => {
            setEditingProject(null);
            load();
          }}
        />
      )}

      {roleModalState && (
        <RoleModal
          project={roleModalState.project}
          role={roleModalState.role}
          skills={skills}
          onClose={() => setRoleModalState(null)}
          onSaved={() => {
            setRoleModalState(null);
            load();
          }}
        />
      )}

      {deleteTarget && (
        <DeleteProjectModal
          project={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onSaved={() => {
            setDeleteTarget(null);
            load();
          }}
        />
      )}

      {suggestState && (
        <CatalogSuggestModal
          project={suggestState.project}
          loading={suggestState.loading}
          suggestion={suggestState.result}
          error={suggestState.error}
          version={suggestState.version}
          onRetry={() => handleSuggest(suggestState.project)}
          onClose={() => setSuggestState(null)}
          onCreated={() => {
            setSuggestState(null);
            load();
          }}
        />
      )}
    </Stack>
  );
}

function levelLabel(level: number): string {
  return { 1: "Entry", 2: "Intermediate", 3: "Advanced" }[level] ?? String(level);
}

function ProjectModal({
  project,
  onClose,
  onSaved,
}: {
  project?: ProjectOut;
  onClose: () => void;
  onSaved: () => void;
}) {
  const api = useApi();
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [status, setStatus] = useState<ProjectStatus>(
    project?.status ?? "active",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleSave() {
    if (!name.trim()) {
      setError(new Error("Project name is required."));
      return;
    }
    setSaving(true);
    try {
      if (project) {
        await api.patchProject(project.id, { name, description, status });
      } else {
        await api.createProject({ name, description, status, roles: [] });
      }
      notifications.show({
        title: project ? "Project updated" : "Project created",
        message: name,
        color: "green",
      });
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      opened
      onClose={onClose}
      title={project ? "Edit project" : "New project"}
    >
      <Stack gap="sm">
        <ErrorAlert error={error} />
        <TextInput
          label="Name"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
        />
        <Textarea
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          minRows={2}
        />
        <Select
          label="Status"
          data={[
            { value: "draft", label: "Draft" },
            { value: "active", label: "Active" },
            { value: "archived", label: "Archived" },
          ]}
          value={status}
          onChange={(v) => setStatus((v as ProjectStatus) ?? "active")}
          allowDeselect={false}
        />
        <Group justify="flex-end" mt="sm">
          <Button variant="subtle" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSave} loading={saving}>
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DeleteProjectModal({
  project,
  onClose,
  onSaved,
}: {
  project: ProjectOut;
  onClose: () => void;
  onSaved: () => void;
}) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);

  async function handleDelete() {
    setBusy(true);
    try {
      await api.deleteProject(project.id);
      notifications.show({
        title: "Project deleted",
        message: `${project.name} was deleted.`,
        color: "green",
      });
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.code === "project_in_use") {
        setConflict(err.message);
      } else {
        notifications.show({
          title: "Couldn't delete project",
          message: describeError(err),
          color: "red",
        });
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleArchive() {
    setBusy(true);
    try {
      await api.patchProject(project.id, { status: "archived" });
      notifications.show({
        title: "Project archived",
        message: `${project.name} was archived.`,
        color: "green",
      });
      onSaved();
    } catch (err) {
      notifications.show({
        title: "Couldn't archive project",
        message: describeError(err),
        color: "red",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal opened onClose={onClose} title="Delete project">
      <Stack gap="sm">
        {conflict ? (
          <>
            <Text size="sm">{conflict}</Text>
            <Group justify="flex-end" mt="sm">
              <Button variant="subtle" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={handleArchive} loading={busy}>
                Archive instead
              </Button>
            </Group>
          </>
        ) : (
          <>
            <Text size="sm">
              Delete &quot;{project.name}&quot;? Its {project.roles.length}{" "}
              role{project.roles.length === 1 ? "" : "s"} will be deleted too.
              This can&apos;t be undone.
            </Text>
            <Group justify="flex-end" mt="sm">
              <Button variant="subtle" onClick={onClose}>
                Cancel
              </Button>
              <Button color="red" onClick={handleDelete} loading={busy}>
                Delete project
              </Button>
            </Group>
          </>
        )}
      </Stack>
    </Modal>
  );
}

function RoleModal({
  project,
  role,
  skills,
  onClose,
  onSaved,
}: {
  project: ProjectOut;
  role: RoleOut | null;
  skills: SkillOut[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const api = useApi();
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [capacity, setCapacity] = useState<number>(role?.capacity ?? 1);
  const [requirements, setRequirements] = useState<RequirementIn[]>(
    role?.requirements.map((r) => ({
      skill_id: r.skill_id,
      required_level: r.required_level,
      requirement_type: r.requirement_type,
      weight: r.weight,
    })) ?? [],
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const skillOptions = skills.map((s) => ({
    value: s.id,
    label: `${s.name} (${s.category})`,
  }));

  function addRequirement() {
    setRequirements((reqs) => [
      ...reqs,
      {
        skill_id: skills[0]?.id ?? "",
        required_level: 1,
        requirement_type: "preferred",
        weight: 1,
      },
    ]);
  }

  function updateRequirement(index: number, patch: Partial<RequirementIn>) {
    setRequirements((reqs) =>
      reqs.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    );
  }

  function removeRequirement(index: number) {
    setRequirements((reqs) => reqs.filter((_, i) => i !== index));
  }

  async function handleSave() {
    if (!name.trim()) {
      setError(new Error("Role name is required."));
      return;
    }
    setSaving(true);
    try {
      if (role) {
        await api.patchRole(role.id, {
          name,
          description,
          capacity,
          requirements,
        });
      } else {
        await api.createRole(project.id, {
          name,
          description,
          capacity,
          requirements,
        });
      }
      notifications.show({
        title: role ? "Role updated" : "Role created",
        message: name,
        color: "green",
      });
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      opened
      onClose={onClose}
      title={role ? `Edit role — ${project.name}` : `Add role — ${project.name}`}
      size="lg"
    >
      <Stack gap="sm">
        <ErrorAlert error={error} />
        <TextInput
          label="Name"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
        />
        <Textarea
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          minRows={2}
        />
        <NumberInput
          label="Capacity"
          min={1}
          max={50}
          value={capacity}
          onChange={(v) => setCapacity(Number(v) || 1)}
        />

        <Group justify="space-between" mt="sm">
          <Text size="sm" fw={500}>
            Requirements
          </Text>
          <Button
            size="xs"
            variant="light"
            leftSection={<Plus size={14} />}
            onClick={addRequirement}
            disabled={skills.length === 0}
          >
            Add requirement
          </Button>
        </Group>

        <Stack gap={8}>
          {requirements.map((req, index) => (
            <Group key={index} align="flex-end" wrap="nowrap">
              <Select
                label={index === 0 ? "Skill" : undefined}
                data={skillOptions}
                value={req.skill_id}
                onChange={(v) =>
                  updateRequirement(index, { skill_id: v ?? req.skill_id })
                }
                searchable
                style={{ flex: 2 }}
              />
              <Select
                label={index === 0 ? "Level" : undefined}
                data={[
                  { value: "1", label: "Entry" },
                  { value: "2", label: "Intermediate" },
                  { value: "3", label: "Advanced" },
                ]}
                value={String(req.required_level)}
                onChange={(v) =>
                  updateRequirement(index, {
                    required_level: Number(v ?? 1),
                  })
                }
                allowDeselect={false}
                style={{ flex: 1 }}
              />
              <Select
                label={index === 0 ? "Type" : undefined}
                data={[
                  { value: "hard_requirement", label: "Required" },
                  { value: "preferred", label: "Preferred" },
                  { value: "learning_opportunity", label: "Learning opportunity" },
                ]}
                value={req.requirement_type}
                onChange={(v) =>
                  updateRequirement(index, {
                    requirement_type:
                      (v as RequirementIn["requirement_type"]) ??
                      req.requirement_type,
                  })
                }
                allowDeselect={false}
                style={{ flex: 1 }}
              />
              <ActionIcon
                color="red"
                variant="subtle"
                onClick={() => removeRequirement(index)}
                mb={4}
              >
                <Trash2 size={16} />
              </ActionIcon>
            </Group>
          ))}
          {requirements.length === 0 && (
            <Text size="sm" c="dimmed">
              No requirements added.
            </Text>
          )}
        </Stack>

        <Group justify="flex-end" mt="sm">
          <Button variant="subtle" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSave} loading={saving}>
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
