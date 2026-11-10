"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState
} from "react";
import type { AuthStatus, AuthUser } from "../../lib/auth";
import {
  fetchCurrentUser,
  forgetLegacyAccessToken,
  loginRequest,
  logoutRequest
} from "../../lib/api";

type AuthContextValue = {
  login: (email: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<boolean>;
  logoutError: string | null;
  isLoggingOut: boolean;
  refresh: () => Promise<void>;
  status: AuthStatus;
  user: AuthUser | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const setUnauthenticated = useCallback(() => {
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  // The session cookie is httpOnly, so the only way to know whether there is one
  // is to ask the API whose it is.
  const refresh = useCallback(async () => {
    forgetLegacyAccessToken();
    setStatus("loading");
    try {
      const currentUser = await fetchCurrentUser();
      setUser(currentUser);
      setStatus("authenticated");
    } catch {
      setUnauthenticated();
    }
  }, [setUnauthenticated]);

  useEffect(() => {
    const restoreTimer = window.setTimeout(() => {
      void refresh();
    }, 0);

    return () => window.clearTimeout(restoreTimer);
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    setLogoutError(null);
    setStatus("loading");
    try {
      const response = await loginRequest(email, password);
      setUser(response.user);
      setStatus("authenticated");
      return response.user;
    } catch (error) {
      setUnauthenticated();
      throw error;
    }
  }, [setUnauthenticated]);

  const logout = useCallback(async () => {
    setLogoutError(null);
    setIsLoggingOut(true);
    try {
      await logoutRequest();
      setUnauthenticated();
      return true;
    } catch {
      setLogoutError("로그아웃을 완료하지 못했습니다. 다시 시도해 주세요.");
      return false;
    } finally {
      setIsLoggingOut(false);
    }
  }, [setUnauthenticated]);

  const value = useMemo<AuthContextValue>(
    () => ({
      login,
      logout,
      logoutError,
      isLoggingOut,
      refresh,
      status,
      user
    }),
    [isLoggingOut, login, logout, logoutError, refresh, status, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used within AuthProvider");
  }

  return value;
}
