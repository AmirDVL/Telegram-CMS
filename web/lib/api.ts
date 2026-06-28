import type { TokenOut } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

const TOKEN_KEY = "tg-cms-token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setTokens(t: TokenOut): void {
  if (typeof window === "undefined") return;
  // Only the short-lived access token is stored in localStorage.
  // The refresh token is stored exclusively in the httpOnly cookie
  // set by the server — it is never accessible to JavaScript.
  localStorage.setItem(TOKEN_KEY, t.access_token);
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/**
 * Call the refresh endpoint directly without going through apiFetch, so we
 * never risk a recursive refresh loop. The browser automatically includes the
 * httpOnly refresh cookie because of `credentials: "include"`.
 */
async function _callRefresh(): Promise<TokenOut | null> {
  try {
    const token = getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify({}),
    });
    if (!res.ok) return null;
    return (await res.json()) as TokenOut;
  } catch {
    return null;
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include", // required for the httpOnly refresh cookie
  });

  if (res.status === 401) {
    // Attempt a transparent token refresh via the httpOnly cookie.
    const refreshed = await _callRefresh();
    if (refreshed) {
      setTokens(refreshed);
      // Retry the original request with the new access token.
      const retryHeaders = {
        ...headers,
        Authorization: `Bearer ${refreshed.access_token}`,
      };
      const retryRes = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers: retryHeaders,
        credentials: "include",
      });
      if (retryRes.ok) {
        if (retryRes.status === 204) return undefined as unknown as T;
        return (await retryRes.json()) as T;
      }
      // Retry also failed — fall through to redirect.
    }
    clearTokens();
    if (
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/login")
    ) {
      window.location.href = "/login";
    }
    throw new ApiError("Unauthorized", 401);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

export async function login(
  username: string,
  password: string,
): Promise<TokenOut> {
  const t = await apiFetch<TokenOut>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setTokens(t);
  return t;
}

export async function logout(): Promise<void> {
  try {
    // Ask the server to clear the httpOnly refresh cookie.
    await apiFetch("/auth/logout", { method: "POST" });
  } catch {
    // Best-effort — clear local state regardless.
  }
  clearTokens();
}
