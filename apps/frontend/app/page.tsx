"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getRoleHomePath } from "./lib/auth";
import { useAuth } from "./components/auth/auth-provider";

export default function Home() {
  const { status, user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated" && user) {
      router.replace(getRoleHomePath(user.role));
      return;
    }
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [router, status, user]);

  return <main className="auth-status-page">페이지를 준비하고 있습니다.</main>;
}
