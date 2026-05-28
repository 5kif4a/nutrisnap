import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircularProgress } from "../components/CircularProgress";
import { MacroBar } from "../components/MacroBar";
import { MealCard } from "../components/MealCard";
import { api } from "../lib/api";
import { humanDate, monthOf, todayISO, weekGrid } from "../lib/date";
import { closeToBot } from "../telegram";
import type { DayResponse, DayStatus, MonthDay } from "../types";

interface Props {
  date: string;
  onDateChange: (iso: string) => void;
}

const emptyDay = (date: string): DayResponse => ({
  date,
  totals: { kcal: 0, protein_g: 0, fat_g: 0, carbs_g: 0 },
  targets: { kcal: null, protein_g: null, fat_g: null, carbs_g: null },
  meals: [],
});

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const STATUS_BG: Record<DayStatus, string> = {
  green: "#22c55e",
  yellow: "#f59e0b",
  red: "#ef4444",
  empty: "var(--tg-border)",
};

export function Dashboard({ date, onDateChange }: Props) {
  const [data, setData] = useState<DayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  // Statuses for the visible week strip — keyed by ISO date. We fetch the
  // months that intersect the week so colours stay correct across month edges.
  const [weekStatus, setWeekStatus] = useState<Map<string, MonthDay>>(
    () => new Map(),
  );

  const load = useCallback(async (d: string) => {
    setLoading(true);
    try {
      setData(await api.getDay(d));
    } catch {
      // Backend hiccup (e.g. 500) — render an empty day instead of an error
      // wall. The bottom-nav still works; user can retry by re-tapping the day.
      setData(emptyDay(d));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(date);
  }, [date, load]);

  const week = useMemo(() => weekGrid(date), [date]);
  // Comma-joined month list — string key so the effect only re-fires when
  // the *months* covered by the week change, not every day navigation.
  const weekMonthsKey = useMemo(
    () => Array.from(new Set([monthOf(week[0]), monthOf(week[6])])).join(","),
    [week],
  );

  // Fetch (and merge) statuses for the months that intersect the visible week.
  useEffect(() => {
    let cancelled = false;
    const months = weekMonthsKey.split(",");
    (async () => {
      try {
        const responses = await Promise.all(months.map((m) => api.getMonth(m)));
        if (cancelled) return;
        const map = new Map<string, MonthDay>();
        for (const r of responses) for (const d of r.days) map.set(d.date, d);
        setWeekStatus(map);
      } catch {
        if (!cancelled) setWeekStatus(new Map());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [weekMonthsKey]);

  const handleDelete = useCallback(
    async (id: string) => {
      await api.deleteMeal(id);
      await load(date);
    },
    [date, load],
  );

  const today = todayISO();

  return (
    <div className="mx-auto max-w-md px-4 pb-32 pt-16">
      {/* Selected day label. */}
      <div className="mb-2 text-center text-sm font-semibold text-tg-text">
        {humanDate(date)}
      </div>

      {/* Week strip — 7 cells Mon→Sun coloured by daily fill status,
          mirroring the legend on the Calendar page. */}
      <div className="mb-4 grid grid-cols-7 gap-1.5">
        {week.map((iso, i) => {
          const day = weekStatus.get(iso);
          const status: DayStatus = day?.status ?? "empty";
          const dayNum = Number(iso.slice(8, 10));
          const isFuture = iso > today;
          const isSelected = iso === date;
          const isToday = iso === today;
          return (
            <button
              key={iso}
              onClick={() => onDateChange(iso)}
              disabled={isFuture}
              aria-label={`${WEEKDAYS[i]} ${dayNum}`}
              aria-current={isSelected ? "date" : undefined}
              className={`flex flex-col items-center gap-0.5 rounded-xl py-1.5 transition active:scale-95 disabled:opacity-30 ${
                status === "empty" ? "text-tg-text" : "text-white"
              } ${isSelected ? "ring-2 ring-[var(--accent)]" : isToday ? "ring-2 ring-tg-link" : ""}`}
              style={{ background: STATUS_BG[status] }}
            >
              <span
                className="text-[10px] font-medium"
                style={{ opacity: status === "empty" ? 0.7 : 0.9 }}
              >
                {WEEKDAYS[i]}
              </span>
              <span className="text-sm font-semibold leading-none">
                {dayNum}
              </span>
            </button>
          );
        })}
      </div>

      {loading && !data ? (
        <div className="py-20 text-center text-tg-hint">Загрузка…</div>
      ) : data ? (
        <>
          <div className="mb-4 flex flex-col items-center rounded-2xl bg-tg-card p-5 shadow-sm">
            <CircularProgress
              value={data.totals.kcal}
              max={data.targets.kcal ?? 0}
              label="ккал"
            />
            {!data.targets.kcal && (
              <p className="mt-3 text-center text-xs text-tg-hint">
                Норма не задана — заполни профиль на вкладке «Профиль».
              </p>
            )}
          </div>

          <div className="mb-4 flex gap-3 rounded-2xl bg-tg-card p-4 shadow-sm">
            <MacroBar
              label="Белки"
              value={data.totals.protein_g}
              target={data.targets.protein_g}
              color="#22c55e"
            />
            <MacroBar
              label="Жиры"
              value={data.totals.fat_g}
              target={data.targets.fat_g}
              color="#f59e0b"
            />
            <MacroBar
              label="Углеводы"
              value={data.totals.carbs_g}
              target={data.targets.carbs_g}
              color="#3b82f6"
            />
          </div>

          <div className="space-y-3">
            {data.meals.length === 0 ? (
              <div className="rounded-2xl bg-tg-card p-6 text-center text-sm text-tg-hint">
                Нет записей за этот день.
              </div>
            ) : (
              data.meals.map((m) => (
                <MealCard key={m.id} meal={m} onDelete={handleDelete} />
              ))
            )}
          </div>
        </>
      ) : null}

      {/* FAB — sits above the liquid-glass nav (z-50) but below modals.
          Wrapped in a centered max-w-md column so it aligns with content
          right-edge on wide viewports instead of flying to the screen edge. */}
      <div
        className="pointer-events-none fixed inset-x-0 z-40"
        style={{
          // Park above the nav pill (nav has 12px safe-area padding + ~62px height).
          bottom: "calc(env(safe-area-inset-bottom, 0px) + 88px)",
        }}
      >
        <div className="mx-auto flex max-w-md justify-end px-4">
          <button
            onClick={closeToBot}
            aria-label="Добавить приём пищи"
            className="liquid-glass pointer-events-auto flex h-14 w-14 items-center justify-center rounded-full text-white active:scale-95"
            style={{
              background:
                "linear-gradient(135deg, var(--accent), rgba(120,92,220,0.95))",
            }}
          >
            <Plus size={26} strokeWidth={2.5} />
          </button>
        </div>
      </div>
    </div>
  );
}
