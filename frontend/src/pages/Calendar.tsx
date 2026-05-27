import { ArrowLeft } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import {
  monthGrid,
  monthLabel,
  shiftMonth,
  thisMonth,
  todayISO,
} from "../lib/date";
import type { DayStatus, MonthResponse } from "../types";

interface Props {
  onSelectDay: (iso: string) => void;
  onBack: () => void;
}

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

export function Calendar({ onSelectDay, onBack }: Props) {
  const [month, setMonth] = useState(thisMonth());
  const [data, setData] = useState<MonthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (m: string) => {
    setError(null);
    try {
      setData(await api.getMonth(m));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load(month);
  }, [month, load]);

  const byDate = new Map((data?.days ?? []).map((d) => [d.date, d]));
  const isFuture = month >= thisMonth();
  const today = todayISO();

  return (
    <div className="mx-auto max-w-md px-4 pb-32 pt-4">
      {/* Header — back to dashboard on the left, month nav on the right.
          pr-12 leaves space for the global gear icon (top-right). */}
      <div className="mb-4 flex items-center gap-2 pr-12">
        <button
          onClick={onBack}
          aria-label="К дневнику"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-card text-tg-text shadow-sm"
        >
          <ArrowLeft size={18} />
        </button>
        <button
          onClick={() => setMonth((m) => shiftMonth(m, -1))}
          aria-label="Предыдущий месяц"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-card text-tg-text shadow-sm"
        >
          ‹
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
          ›
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl bg-red-100 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

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
                onClick={() => onSelectDay(iso)}
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
