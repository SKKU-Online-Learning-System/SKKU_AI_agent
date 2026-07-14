"use client";

import { AppShell } from "../components/auth/app-shell";
import { ProtectedRoute } from "../components/auth/protected-route";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute allowedRoles={["admin"]}>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}
