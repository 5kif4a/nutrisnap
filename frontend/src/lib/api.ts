import { getInitData } from "../telegram";
import type {
  DayResponse,
  MonthResponse,
  ProfileUpdate,
  UserProfile,
} from "../types";

// Empty base in dev → Vite proxies /api to FastAPI. Set VITE_API_URL in prod.
const BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Init-Data": getInitData(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  getMe: () => request<UserProfile>("/api/me"),

  updateMe: (payload: ProfileUpdate) =>
    request<UserProfile>("/api/me", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  getDay: (date?: string) =>
    request<DayResponse>(`/api/day${date ? `?date=${date}` : ""}`),

  getMonth: (month?: string) =>
    request<MonthResponse>(`/api/month${month ? `?month=${month}` : ""}`),

  deleteMeal: (id: string) =>
    request<void>(`/api/meal/${id}`, { method: "DELETE" }),
};
