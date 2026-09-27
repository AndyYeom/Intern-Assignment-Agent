"use client";

import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { ApiBaseProvider } from "@/lib/api-context";

export function Providers({
  apiBaseUrl,
  children,
}: {
  apiBaseUrl: string;
  children: React.ReactNode;
}) {
  return (
    <MantineProvider defaultColorScheme="light">
      <Notifications position="top-right" />
      <ApiBaseProvider apiBaseUrl={apiBaseUrl}>{children}</ApiBaseProvider>
    </MantineProvider>
  );
}
