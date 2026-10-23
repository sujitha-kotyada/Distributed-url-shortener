import type { TokenResponse, UrlItem, UrlStatsResponse, User } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const TOKEN_KEY = "url_shortener_jwt_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const token = getStoredToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  if (options.body && typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail = `Request failed with status ${response.status}`;
    try {
      const errJson = await response.json();
      if (errJson && errJson.detail) {
        errorDetail = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // ignore json parse error
    }
    throw new Error(errorDetail);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  async register(email: string, password: string): Promise<User> {
    return request<User>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async login(email: string, password: string): Promise<TokenResponse> {
    const res = await request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setStoredToken(res.access_token);
    return res;
  },

  logout(): void {
    clearStoredToken();
  },

  async getMe(): Promise<User> {
    return request<User>("/api/v1/auth/me");
  },

  async createUrl(url: string): Promise<UrlItem> {
    return request<UrlItem>("/api/v1/urls", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  },

  async getMyUrls(limit = 50, offset = 0): Promise<UrlItem[]> {
    return request<UrlItem[]>(`/api/v1/urls/my?limit=${limit}&offset=${offset}`);
  },

  async getUrlStats(shortCode: string, days = 7, interval: "hour" | "day" = "day"): Promise<UrlStatsResponse> {
    return request<UrlStatsResponse>(`/api/v1/urls/${encodeURIComponent(shortCode)}/stats?days=${days}&interval=${interval}`);
  },
};
