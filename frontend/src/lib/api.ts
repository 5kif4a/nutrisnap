import { getInitData } from "../telegram";
import type {
  BulkAddRequest,
  CreateCustomFoodRequest,
  DayResponse,
  MealEntryResolveResponse,
  MealOut,
  MealType,
  MonthResponse,
  ProfileUpdate,
  QuickAddFoodOut,
  QuickAddRequest,
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

  getRecentFoods: (params?: { mealType?: MealType; limit?: number }) =>
    request<QuickAddFoodOut[]>(
      `/api/foods/recent${buildQuery({
        meal_type: params?.mealType,
        limit: params?.limit,
      })}`,
    ),

  getFrequentFoods: (params?: {
    mealType?: MealType;
    days?: number;
    limit?: number;
  }) =>
    request<QuickAddFoodOut[]>(
      `/api/foods/frequent${buildQuery({
        meal_type: params?.mealType,
        days: params?.days,
        limit: params?.limit,
      })}`,
    ),

  searchFoods: (params: { q: string; limit?: number }) =>
    request<QuickAddFoodOut[]>(
      `/api/foods/search${buildQuery({ q: params.q, limit: params.limit })}`,
    ),

  quickAddMeal: (payload: QuickAddRequest) =>
    request<MealOut>(`/api/meals/quick-add`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  bulkAddMeal: (payload: BulkAddRequest) =>
    request<MealOut>(`/api/meals/bulk`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createCustomFood: (payload: CreateCustomFoodRequest) =>
    request<QuickAddFoodOut>(`/api/foods/custom`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  entryFromPhoto: async (file: File): Promise<MealEntryResolveResponse> => {
    // Multipart upload — fetch must NOT set Content-Type; the browser fills
    // it with the multipart boundary. The X-Init-Data auth header is still
    // required.
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/api/meals/from-photo`, {
      method: "POST",
      headers: { "X-Init-Data": getInitData() },
      body: form,
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${body || res.statusText}`);
    }
    return (await res.json()) as MealEntryResolveResponse;
  },

  entryFromText: (text: string) =>
    request<MealEntryResolveResponse>(`/api/meals/from-text`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
};

function buildQuery(
  params: Record<string, string | number | undefined>,
): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null,
  );
  if (entries.length === 0) return "";
  return (
    "?" +
    entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&")
  );
}
