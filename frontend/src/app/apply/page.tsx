"use client";

import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Center,
  CopyButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { Dropzone, type FileRejection } from "@mantine/dropzone";
import { AlertTriangle, Check, Copy, FileText, Upload, X } from "lucide-react";
import { useApi } from "@/lib/api-context";
import { ApiError } from "@/lib/api";
import { describeError } from "@/lib/format";
import type { ApplicationPublic } from "@/lib/types";

const MAX_SIZE = 10 * 1024 * 1024;
const GITHUB_URL_RE = /^https:\/\/github\.com\/[A-Za-z0-9-]+\/?$/;

interface FormValues {
  name: string;
  email: string;
  github_url: string;
  portfolio_url: string;
}

type SubmitState = "default" | "validating" | "uploading" | "success" | "error";

export default function ApplyPage() {
  const api = useApi();
  const [state, setState] = useState<SubmitState>("default");
  const [resume, setResume] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [publicInfo, setPublicInfo] = useState<ApplicationPublic | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  const form = useForm<FormValues>({
    mode: "controlled",
    initialValues: {
      name: "",
      email: "",
      github_url: "",
      portfolio_url: "",
    },
    validate: {
      name: (v) => (v.trim().length === 0 ? "Name is required" : null),
      email: (v) =>
        /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) ? null : "Enter a valid email address",
      github_url: (v) =>
        GITHUB_URL_RE.test(v.trim())
          ? null
          : "Enter a GitHub profile URL, e.g. https://github.com/username",
      portfolio_url: (v) => {
        if (!v) return null;
        try {
          new URL(v);
          return null;
        } catch {
          return "Enter a valid URL";
        }
      },
    },
  });

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!applicationId) return;
    if (!publicInfo) return;
    if (publicInfo.status !== "submitted" && publicInfo.status !== "processing") {
      return;
    }
    pollTimer.current = setTimeout(async () => {
      try {
        const info = await api.getApplication(applicationId);
        setPublicInfo(info);
        setPollError(null);
      } catch (err) {
        setPollError(describeError(err));
      }
    }, 5000);
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [applicationId, publicInfo, api]);

  function handleDrop(files: File[]) {
    setFileError(null);
    setResume(files[0] ?? null);
  }

  function handleReject(rejections: FileRejection[]) {
    const first = rejections[0];
    if (!first) return;
    const code = first.errors[0]?.code;
    if (code === "file-too-large") {
      setFileError("File is too large. Maximum size is 10 MB.");
    } else if (code === "file-invalid-type") {
      setFileError("Only PDF files are accepted.");
    } else {
      setFileError(first.errors[0]?.message ?? "File was rejected.");
    }
  }

  async function handleSubmit(values: FormValues) {
    setSubmitError(null);
    if (!resume) {
      setFileError("Please attach your resume (PDF, max 10 MB).");
      return;
    }
    setState("validating");
    try {
      setState("uploading");
      const created = await api.submitApplication({
        name: values.name.trim(),
        email: values.email.trim(),
        github_url: values.github_url.trim(),
        portfolio_url: values.portfolio_url.trim() || undefined,
        resume,
      });
      setApplicationId(created.id);
      setState("success");
      try {
        const info = await api.getApplication(created.id);
        setPublicInfo(info);
      } catch {
        // Non-fatal: we still show the success state with the ID.
      }
    } catch (err) {
      setState("error");
      if (err instanceof ApiError && err.code === "validation_error" && err.details) {
        for (const detail of err.details) {
          const field = String(detail.field ?? detail.loc ?? "");
          const msg = String(detail.message ?? detail.msg ?? "Invalid value");
          if (field && field in form.values) {
            form.setFieldError(field as keyof FormValues, msg);
          }
        }
      }
      setSubmitError(describeError(err));
    }
  }

  if (state === "success" && applicationId) {
    return (
      <CenteredShell>
        <Paper withBorder radius="md" p="xl" shadow="sm">
          <Stack gap="md">
            <Group gap="xs">
              <Check color="var(--mantine-color-green-6)" size={22} />
              <Title order={3}>Application submitted</Title>
            </Group>
            <Text c="dimmed" size="sm">
              Thank you for applying. Keep your application ID for reference.
            </Text>
            <Group
              gap="xs"
              wrap="nowrap"
              p="sm"
              style={{
                border: "1px solid var(--mantine-color-gray-3)",
                borderRadius: 8,
              }}
            >
              <Text ff="monospace" size="sm" style={{ wordBreak: "break-all" }}>
                {applicationId}
              </Text>
              <CopyButton value={applicationId}>
                {({ copied, copy }) => (
                  <Tooltip label={copied ? "Copied" : "Copy"}>
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={copy}
                      leftSection={
                        copied ? <Check size={14} /> : <Copy size={14} />
                      }
                    >
                      {copied ? "Copied" : "Copy"}
                    </Button>
                  </Tooltip>
                )}
              </CopyButton>
            </Group>

            <Box>
              <Text size="sm" fw={500} mb={4}>
                Status
              </Text>
              {publicInfo ? (
                <Stack gap={4}>
                  <Group gap="xs">
                    {(publicInfo.status === "submitted" ||
                      publicInfo.status === "processing") && (
                      <Loader size="xs" />
                    )}
                    <Text size="sm">{friendlyStatus(publicInfo.status)}</Text>
                  </Group>
                  <Text size="sm" c="dimmed">
                    {publicInfo.message}
                  </Text>
                </Stack>
              ) : (
                <Group gap="xs">
                  <Loader size="xs" />
                  <Text size="sm" c="dimmed">
                    Checking status…
                  </Text>
                </Group>
              )}
              {pollError && (
                <Text size="xs" c="red" mt={4}>
                  {pollError}
                </Text>
              )}
            </Box>
          </Stack>
        </Paper>
      </CenteredShell>
    );
  }

  return (
    <CenteredShell>
      <Stack gap={4} mb="lg">
        <Title order={2}>Utechia Internship</Title>
        <Text c="dimmed">Apply for an internship project</Text>
      </Stack>

      <Paper withBorder radius="md" p="xl" shadow="sm">
        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack gap="md">
            {submitError && (
              <Alert
                color="red"
                variant="light"
                icon={<AlertTriangle size={18} />}
                title="Couldn't submit your application"
              >
                {submitError}
              </Alert>
            )}

            <TextInput
              label="Name"
              placeholder="Ada Lovelace"
              required
              {...form.getInputProps("name")}
            />
            <TextInput
              label="Email"
              placeholder="ada@example.com"
              required
              {...form.getInputProps("email")}
            />
            <TextInput
              label="GitHub URL"
              placeholder="https://github.com/ada"
              required
              {...form.getInputProps("github_url")}
            />
            <TextInput
              label="Portfolio URL"
              placeholder="https://ada.dev (optional)"
              {...form.getInputProps("portfolio_url")}
            />

            <Box>
              <Text size="sm" fw={500} mb={4}>
                Resume <span style={{ color: "var(--mantine-color-red-6)" }}>*</span>
              </Text>
              {resume ? (
                <Group
                  justify="space-between"
                  p="sm"
                  style={{
                    border: "1px solid var(--mantine-color-gray-3)",
                    borderRadius: 8,
                  }}
                >
                  <Group gap="xs">
                    <FileText size={18} />
                    <Text size="sm">{resume.name}</Text>
                  </Group>
                  <Button
                    variant="subtle"
                    size="xs"
                    color="red"
                    onClick={() => setResume(null)}
                  >
                    Remove
                  </Button>
                </Group>
              ) : (
                <Dropzone
                  onDrop={handleDrop}
                  onReject={handleReject}
                  maxSize={MAX_SIZE}
                  accept={{ "application/pdf": [".pdf"] }}
                  multiple={false}
                >
                  <Group
                    justify="center"
                    gap="md"
                    style={{ minHeight: 100, pointerEvents: "none" }}
                  >
                    <Dropzone.Accept>
                      <Upload size={28} />
                    </Dropzone.Accept>
                    <Dropzone.Reject>
                      <X size={28} />
                    </Dropzone.Reject>
                    <Dropzone.Idle>
                      <FileText size={28} />
                    </Dropzone.Idle>
                    <div>
                      <Text size="sm">Drag your resume here or click to browse</Text>
                      <Text size="xs" c="dimmed">
                        PDF only, max 10 MB
                      </Text>
                    </div>
                  </Group>
                </Dropzone>
              )}
              {fileError && (
                <Text size="xs" c="red" mt={4}>
                  {fileError}
                </Text>
              )}
            </Box>

            <Button
              type="submit"
              loading={state === "validating" || state === "uploading"}
              fullWidth
              mt="sm"
            >
              {state === "uploading" ? "Submitting…" : "Submit application"}
            </Button>
          </Stack>
        </form>
      </Paper>
    </CenteredShell>
  );
}

function friendlyStatus(status: ApplicationPublic["status"]): string {
  switch (status) {
    case "submitted":
      return "Submitted — waiting to be processed";
    case "processing":
      return "Processing your application";
    case "ready":
      return "Ready — your application has been reviewed";
    case "failed":
      return "We ran into an issue processing your application";
    default:
      return status;
  }
}

function CenteredShell({ children }: { children: React.ReactNode }) {
  return (
    <Center mih="100vh" bg="var(--mantine-color-gray-0)">
      <Box w="100%" maw={480} px="md" py="xl">
        {children}
      </Box>
    </Center>
  );
}
