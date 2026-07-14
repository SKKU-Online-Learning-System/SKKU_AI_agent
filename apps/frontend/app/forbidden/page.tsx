"use client";

import Link from "next/link";
import { getRoleHomePath } from "../lib/auth";
import { useAuth } from "../components/auth/auth-provider";

export default function ForbiddenPage() {
  const { user } = useAuth();
  const homePath = user ? getRoleHomePath(user.role) : "/login";

  return (
    <main className="auth-status-page">
      <section>
        <h1>403</h1>
        <p>이 페이지에 접근할 권한이 없습니다.</p>
        <Link href={homePath}>{user ? "내 대시보드로 이동" : "로그인으로 이동"}</Link>
      </section>
    </main>
  );
}
