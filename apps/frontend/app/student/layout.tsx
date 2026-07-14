"use client";

import { AppShell } from "../components/auth/app-shell";
import { ProtectedRoute } from "../components/auth/protected-route";

export default function StudentLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute allowedRoles={["student"]}>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}
