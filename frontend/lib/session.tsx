"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  apiRequest,
  jsonBody,
  TOKEN_STORAGE_KEY,
  type User,
  type UserRole,
} from "@/lib/api";

type SessionContextValue = {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (identifier: string, password: string) => Promise<User>;
  demoLogin: (role: UserRole) => Promise<User>;
  logout: () => void;
  refresh: () => Promise<User | null>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const saveToken = useCallback((nextToken: string | null) => {
    setToken(nextToken);
    if (nextToken) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  }, []);

  const loadUser = useCallback(
    async (activeToken: string) => {
      const nextUser = await apiRequest<User>("/auth/me", {}, activeToken);
      setUser(nextUser);
      return nextUser;
    },
    [],
  );

  useEffect(() => {
    const storedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!storedToken) {
      setLoading(false);
      return;
    }
    setToken(storedToken);
    loadUser(storedToken)
      .catch(() => {
        window.localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, [loadUser]);

  const authenticate = useCallback(
    async (path: string, payload: unknown) => {
      const response = await apiRequest<{ access_token: string }>(
        path,
        { method: "POST", ...jsonBody(payload) },
        null,
      );
      saveToken(response.access_token);
      return await loadUser(response.access_token);
    },
    [loadUser, saveToken],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      user,
      token,
      loading,
      login: (identifier, password) =>
        authenticate("/auth/login", { identifier, password }),
      demoLogin: (role) => authenticate("/auth/demo-login", { role }),
      logout: () => {
        saveToken(null);
        setUser(null);
      },
      refresh: async () => {
        if (!token) {
          return null;
        }
        return await loadUser(token);
      },
    }),
    [authenticate, loadUser, loading, saveToken, token, user],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return value;
}
