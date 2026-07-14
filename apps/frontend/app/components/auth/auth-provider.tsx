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
  ApiError,
  clearAccessToken,
  fetchCurrentUser,
  loginRequest,
  readAccessToken,
  saveAccessToken
} from "../../lib/api";

type AuthContextValue = {
  accessToken: string | null;
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
  const [accessToken, setAccessToken] = useState<string | null>(null);

  const setUnauthenticated = useCallback(() => {
    clearAccessToken();
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const refresh = useCallback(async () => {
    const storedToken = readAccessToken();
    if (!storedToken) {
      setUnauthenticated();
      return;
    }

    setStatus("loading");
    try {
      const currentUser = await fetchCurrentUser(storedToken);
      setAccessToken(storedToken);
      setUser(currentUser);
      setStatus("authenticated");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUnauthenticated();
        return;
      }
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
      saveAccessToken(response.access_token);
      setAccessToken(response.access_token);
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
  }, [setUnauthenticated]);

  const value = useMemo<AuthContextValue>(
    () => ({
      accessToken,
      login,
      logout,
      refresh,
      status,
      user
    }),
    [accessToken, login, logout, refresh, status, user]
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
