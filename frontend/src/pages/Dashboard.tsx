import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CircularProgress } from "../components/CircularProgress";
import { MacroBar } from "../components/MacroBar";
import { MealCard } from "../components/MealCard";
import { api } from "../lib/api";
import { humanDate, shiftDayISO, todayISO } from "../lib/date";
import { closeToBot } from "../telegram";
import type { DayResponse } from "../types";

interface Props {
  date: string;
  onDateChange: (iso: string) => void;
}

export function Dashboard({ date, onDateChange }: Props) {
  const [data, setData] = useState<DayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getDay(d));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(date);
  }, [date, load]);

  const handleDelete = useCallback(
    async (id: string) => {
      await api.deleteMeal(id);
      await load(date);
    },
    [date, load],
  );

  const shiftDay = (delta: number) => onDateChange(shiftDayISO(date, delta));

  const isToday = date === todayISO();

  return (
    <div className="mx-auto max-w-md px-4 pb-32 pt-4">
      {/* Header — date navigation. Calendar reachable via bottom-nav tab. */}
      <div className="mb-4 flex items-center gap-2 pr-12">
        <button
          onClick={() => shiftDay(-1)}
          aria-label="Предыдущий день"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-card text-tg-text shadow-sm"
        >
          <ChevronLeft size={20} />
        </button>
        <span className="flex-1 text-center font-semibold text-tg-text">
          {humanDate(date)}
        </span>
        <button
          onClick={() => shiftDay(1)}
          disabled={isToday}
          aria-label="Следующий день"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-card text-tg-text shadow-sm disabled:opacity-30"
        >
          <ChevronRight size={20} />
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl bg-red-100 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

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
          Positioned right-bottom, fixed to the viewport. */}
      <button
        onClick={closeToBot}
        aria-label="Добавить приём пищи"
        className="liquid-glass fixed right-5 z-40 flex h-14 w-14 items-center justify-center rounded-full text-white active:scale-95"
        style={{
          background:
            "linear-gradient(135deg, var(--accent), rgba(120,92,220,0.95))",
          // Park above the nav pill (nav has 12px safe-area padding + ~62px height).
          bottom: "calc(env(safe-area-inset-bottom, 0px) + 88px)",
        }}
      >
        <Plus size={26} strokeWidth={2.5} />
      </button>
    </div>
  );
}
