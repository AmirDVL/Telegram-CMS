import type {
  TokenOut,
  AISettings,
  AITestRequest,
  AITestResponse,
  Tenant,
} from "./types";

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

// ── AI Settings ─────────────────────────────────────────────────────────────

export async function getAISettings(channelId: number): Promise<AISettings> {
  return apiFetch<AISettings>(`/source-channels/${channelId}/ai`);
}

export async function updateAISettings(
  channelId: number,
  data: Partial<AISettings>,
): Promise<AISettings> {
  return apiFetch<AISettings>(`/source-channels/${channelId}/ai`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function testAITransform(
  channelId: number,
  data: AITestRequest,
): Promise<AITestResponse> {
  return apiFetch<AITestResponse>(`/source-channels/${channelId}/ai/test`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ── Tenants ─────────────────────────────────────────────────────────────────

export async function listTenants(): Promise<Tenant[]> {
  return apiFetch<Tenant[]>("/tenants");
}

export async function getTenant(tenantId: number): Promise<Tenant> {
  return apiFetch<Tenant>(`/tenants/${tenantId}`);
}

export async function createTenant(
  data: Partial<Tenant>,
): Promise<Tenant> {
  return apiFetch<Tenant>("/tenants", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateTenant(
  tenantId: number,
  data: Partial<Tenant>,
): Promise<Tenant> {
  return apiFetch<Tenant>(`/tenants/${tenantId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteTenant(tenantId: number): Promise<void> {
  return apiFetch<void>(`/tenants/${tenantId}`, { method: "DELETE" });
}
