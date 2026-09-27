import type { Metadata } from "next";
import { connection } from "next/server";
import { ColorSchemeScript, mantineHtmlProps } from "@mantine/core";
import "@mantine/core/styles.css";
import "@mantine/dropzone/styles.css";
import "@mantine/notifications/styles.css";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Utechia Internship",
  description: "Utechia internship application and assignment platform",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Force this layout to render per-request (never statically cached) so the
  // API base URL is always read from the live server environment, not
  // frozen at build time.
  await connection();

  const apiBaseUrl =
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8000";

  return (
    <html lang="en" {...mantineHtmlProps}>
      <head>
        <ColorSchemeScript defaultColorScheme="light" />
      </head>
      <body>
        <Providers apiBaseUrl={apiBaseUrl}>{children}</Providers>
      </body>
    </html>
  );
}
