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
    <main className="login-page">
      <section className="login-panel" aria-labelledby="login-title">
        <div>
          <span>SKKU Course Agent</span>
          <h1 id="login-title">로그인</h1>
          <p>강의자료 기반 AI 코스 에이전트에 접속합니다.</p>
        </div>
        <form onSubmit={handleSubmit}>
          <label>
            이메일
            <input
              autoComplete="email"
              name="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label>
            비밀번호
            <input
              autoComplete="current-password"
              name="password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          {errorMessage ? <p role="alert">{errorMessage}</p> : null}
          <button disabled={isSubmitting || status === "loading"} type="submit">
            {isSubmitting ? "로그인 중" : "로그인"}
          </button>
        </form>
      </section>
    </main>
  );
}
