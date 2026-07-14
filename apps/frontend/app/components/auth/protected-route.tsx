"use client";

import type { UserRole } from "@skku-course-agent/shared";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { canAccessRole } from "../../lib/auth";
import { useAuth } from "./auth-provider";

type ProtectedRouteProps = {
  allowedRoles: UserRole[];
  children: React.ReactNode;
};

export function ProtectedRoute({ allowedRoles, children }: ProtectedRouteProps) {
  const { status, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    if (status === "authenticated" && user && !canAccessRole(user.role, allowedRoles)) {
      router.replace("/forbidden");
    }
  }, [allowedRoles, pathname, router, status, user]);

  if (status === "loading") {
    return <main className="auth-status-page">로그인 상태를 확인하고 있습니다.</main>;
  }

  if (!user || !canAccessRole(user.role, allowedRoles)) {
    return <main className="auth-status-page">페이지 접근 권한을 확인하고 있습니다.</main>;
  }

  return <>{children}</>;
}
