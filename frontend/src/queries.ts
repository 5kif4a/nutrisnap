import { queryOptions } from "@tanstack/react-query";
import { api } from "./lib/api";

export const meQuery = () =>
  queryOptions({
    queryKey: ["me"],
    queryFn: () => api.getMe(),
    staleTime: 60_000,
  });

export const dayQuery = (date: string) =>
  queryOptions({
    queryKey: ["day", date],
    queryFn: () => api.getDay(date),
    staleTime: 30_000,
  });

export const monthQuery = (month: string) =>
  queryOptions({
    queryKey: ["month", month],
    queryFn: () => api.getMonth(month),
    staleTime: 60_000,
  });

export const recentFoodsQuery = (limit = 20) =>
  queryOptions({
    queryKey: ["foods", "recent", limit],
    queryFn: () => api.getRecentFoods({ limit }),
    staleTime: 30_000,
  });

export const frequentFoodsQuery = (limit = 20) =>
  queryOptions({
    queryKey: ["foods", "frequent", limit],
    queryFn: () => api.getFrequentFoods({ limit }),
    staleTime: 30_000,
  });

export const searchFoodsQuery = (q: string, limit = 25) =>
  queryOptions({
    queryKey: ["foods", "search", q, limit],
    queryFn: () => api.searchFoods({ q, limit }),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
  });
