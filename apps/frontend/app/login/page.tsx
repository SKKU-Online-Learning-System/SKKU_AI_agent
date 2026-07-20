"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../components/auth/auth-provider";
import { ApiError } from "../lib/api";
import { getRoleHomePath } from "../lib/auth";

export default function LoginPage() {
  const { login, status, user } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (status === "authenticated" && user) {
      router.replace(getRoleHomePath(user.role));
    }
  }, [router, status, user]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      const loggedInUser = await login(email, password);
      router.replace(getRoleHomePath(loggedInUser.role));
    } catch (error) {
      if (error instanceof ApiError) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("로그인 중 문제가 발생했습니다.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="icampus-login-page">
      <section className="icampus-login" aria-labelledby="login-title">
        <h1 id="login-title">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="성균관대학교 i-Campus" src="/icampus-login-logo.png" />
        </h1>
        <form onSubmit={handleSubmit}>
          <label>
            <span>아이디 또는 이메일</span>
            <input
              autoComplete="username"
              name="email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="ID"
              required
              type="email"
              value={email}
            />
          </label>
          <label>
            <span>비밀번호</span>
            <input
              autoComplete="current-password"
              name="password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password"
              required
              type="password"
              value={password}
            />
          </label>
          {errorMessage ? <p role="alert">{errorMessage}</p> : null}
          <button disabled={isSubmitting || status === "loading"} type="submit">
            {isSubmitting ? "LOGIN..." : "LOGIN"}
          </button>
        </form>
        <p className="icampus-login-help">
          성균관대학교 강의자료 기반 AI 코스 에이전트입니다.
        </p>
      </section>
    </main>
  );
}
