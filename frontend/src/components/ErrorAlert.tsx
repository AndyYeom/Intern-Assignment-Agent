import { Alert } from "@mantine/core";
import { AlertTriangle } from "lucide-react";
import { describeError } from "@/lib/format";

export function ErrorAlert({
  error,
  title = "Something went wrong",
}: {
  error: unknown;
  title?: string;
}) {
  if (!error) return null;
  return (
    <Alert
      color="red"
      variant="light"
      icon={<AlertTriangle size={18} />}
      title={title}
    >
      {describeError(error)}
    </Alert>
  );
}
