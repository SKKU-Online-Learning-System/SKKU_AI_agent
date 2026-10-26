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
  logout: () => void;
  refresh: () => Promise<void>;
  status: AuthStatus;
  user: AuthUser | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

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

  const logout = useCallback(() => {
    setUnauthenticated();
    // Best effort: a cookie the API never cleared still expires on its own.
    void logoutRequest().catch(() => undefined);
  }, [setUnauthenticated]);

  const value = useMemo<AuthContextValue>(
    () => ({
      login,
      logout,
      refresh,
      status,
      user
    }),
    [login, logout, refresh, status, user]
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
