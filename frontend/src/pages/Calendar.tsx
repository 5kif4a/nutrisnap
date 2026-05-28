import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { monthQuery } from "../queries";
import {
  monthGrid,
  monthLabel,
  shiftMonth,
  thisMonth,
  todayISO,
} from "../lib/date";
import type { DayStatus } from "../types";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const STATUS_BG: Record<DayStatus, string> = {
  green: "#22c55e",
  yellow: "#f59e0b",
  red: "#ef4444",
  empty: "var(--tg-border)",
};

const LEGEND: { status: DayStatus; label: string }[] = [
  { status: "green", label: "В норме" },
  { status: "yellow", label: "Немного" },
  { status: "red", label: "Мало" },
  { status: "empty", label: "Нет записей" },
];

export function Calendar() {
  const navigate = useNavigate();
  const [month, setMonth] = useState(thisMonth());

  const { data } = useQuery({
    ...monthQuery(month),
    placeholderData: { month, target_kcal: null, days: [] },
  });

  const byDate = new Map((data?.days ?? []).map((d) => [d.date, d]));
  const isFuture = month >= thisMonth();
  const today = todayISO();

  return (
    <div className="mx-auto max-w-md px-4 pb-32 pt-16">
      {/* Month navigation header. */}
      <div className="mb-4 flex items-center gap-2">
        <button
          onClick={() => setMonth((m) => shiftMonth(m, -1))}
          aria-label="Предыдущий месяц"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-card text-tg-text shadow-sm"
        >
          <ChevronLeft size={20} />
        </button>
        <span className="flex-1 text-center font-semibold capitalize text-tg-text">
          {monthLabel(month)}
        </span>
        <button
          onClick={() => setMonth((m) => shiftMonth(m, 1))}
          disabled={isFuture}
          aria-label="Следующий месяц"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-card text-tg-text shadow-sm disabled:opacity-30"
        >
          <ChevronRight size={20} />
        </button>
      </div>

      <div className="rounded-2xl bg-tg-card p-3 shadow-sm">
        <div className="mb-1 grid grid-cols-7 gap-1">
          {WEEKDAYS.map((w) => (
            <div
              key={w}
              className="py-1 text-center text-xs font-medium text-tg-hint"
            >
              {w}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {monthGrid(month).map((iso, i) => {
            if (!iso) return <div key={`b${i}`} />;
            const day = byDate.get(iso);
            const status: DayStatus = day?.status ?? "empty";
            const dayNum = Number(iso.slice(8, 10));
            const future = iso > today;
            return (
              <button
                key={iso}
                disabled={future}
                onClick={() =>
                  void navigate({ to: "/dashboard", search: { date: iso } })
                }
                className={`relative aspect-square rounded-lg text-sm font-medium transition active:scale-95 disabled:opacity-30 ${
                  status === "empty" ? "text-tg-text" : "text-white"
                } ${iso === today ? "ring-2 ring-tg-link" : ""}`}
                style={{ background: STATUS_BG[status] }}
                title={day ? `${Math.round(day.kcal)} ккал` : undefined}
              >
                {dayNum}
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 rounded-2xl bg-tg-card p-4 shadow-sm">
        {LEGEND.map((l) => (
          <div key={l.status} className="flex items-center gap-2 text-xs">
            <span
              className="inline-block h-3 w-3 rounded"
              style={{ background: STATUS_BG[l.status] }}
            />
            <span className="text-tg-hint">{l.label}</span>
          </div>
        ))}
      </div>

      <p className="mt-3 text-center text-xs text-tg-hint">
        Цвет — доля дневной нормы калорий. Тап по дню → детали.
      </p>
    </div>
  );
}
