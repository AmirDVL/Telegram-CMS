"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { apiFetch, login as doLogin, logout as doLogout } from "./api";
import type { Admin } from "./types";

interface AuthCtx {
  admin: Admin | null;
  loading: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>({
  admin: null,
  loading: true,
  login: async () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // apiFetch will transparently attempt a token refresh via the httpOnly
    // cookie if the access token is missing or expired — no explicit guard needed.
    apiFetch<Admin>("/auth/me")
      .then(setAdmin)
      .catch(() => setAdmin(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    await doLogin(username, password);
    const me = await apiFetch<Admin>("/auth/me");
    setAdmin(me);
    router.push("/queue");
  };

  const logout = async () => {
    await doLogout();
    setAdmin(null);
    router.push("/login");
  };

  return (
    <Ctx.Provider value={{ admin, loading, login, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  return useContext(Ctx);
}
