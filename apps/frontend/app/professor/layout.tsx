"use client";

import { AppShell } from "../components/auth/app-shell";
import { ProtectedRoute } from "../components/auth/protected-route";

export default function ProfessorLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute allowedRoles={["professor"]}>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}
