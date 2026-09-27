"use client";

import { AppShell, Group, NavLink, Text, Title } from "@mantine/core";
import { usePathname, useRouter } from "next/navigation";
import { ClipboardList, FolderKanban, Users } from "lucide-react";

const NAV_ITEMS = [
  { label: "Applicants", href: "/manager/applicants", icon: Users },
  { label: "Projects", href: "/manager/projects", icon: FolderKanban },
  { label: "Assignments", href: "/manager/assignments", icon: ClipboardList },
];

export default function ManagerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <AppShell navbar={{ width: 240, breakpoint: "sm" }} padding="lg">
      <AppShell.Navbar p="md">
        <Group mb="lg" px={4}>
          <Title order={4}>Utechia</Title>
        </Group>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600} px={4} mb={4}>
          Manager
        </Text>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = pathname?.startsWith(item.href);
          return (
            <NavLink
              key={item.href}
              label={item.label}
              leftSection={<Icon size={18} />}
              active={active}
              onClick={() => router.push(item.href)}
              style={{ borderRadius: 8 }}
            />
          );
        })}
      </AppShell.Navbar>
      <AppShell.Main>{children}</AppShell.Main>
    </AppShell>
  );
}
