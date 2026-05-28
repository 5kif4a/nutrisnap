import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircularProgress } from "../components/CircularProgress";
import { FabActionSheet } from "../components/FabActionSheet";
import { FoodForm } from "../components/FoodForm";
import { MacroBar } from "../components/MacroBar";
import { MealCard } from "../components/MealCard";
import { MealTypeSheet } from "../components/MealTypeSheet";
import { api } from "../lib/api";
import { humanDate, monthOf, todayISO, weekGrid } from "../lib/date";
import type {
  BulkAddItem,
  DayResponse,
  DayStatus,
  MealType,
  MonthDay,
  QuickAddFoodOut,
  ResolvedItem,
} from "../types";

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

  // FAB action-sheet state. `pendingItems` is the basket the user is about
  // to save (either from a vision-resolved photo OR a single manually-created
  // food). When non-empty + mealPickerOpen → MealTypeSheet shows.
  const [actionSheetOpen, setActionSheetOpen] = useState(false);
  const [foodFormOpen, setFoodFormOpen] = useState(false);
  const [pendingItems, setPendingItems] = useState<BulkAddItem[]>([]);
  const [mealPickerOpen, setMealPickerOpen] = useState(false);
  const [savingMeal, setSavingMeal] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

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

  // Photo-resolved items from FabActionSheet → open meal-type picker.
  const handlePhotoResolved = useCallback((items: ResolvedItem[]) => {
    setPendingItems(
      items.map((it) => ({
        food_name: it.food_name,
        amount: it.amount,
        unit: it.unit,
        weight_g: it.weight_g,
        kcal: it.kcal,
        protein_g: it.protein_g,
        fat_g: it.fat_g,
        carbs_g: it.carbs_g,
        food_id: it.food_id ?? null,
      })),
    );
    setActionSheetOpen(false);
    setMealPickerOpen(true);
  }, []);

  // Newly-created custom food from FAB → seed pending basket with 1 item
  // and jump to meal-type picker (no extra weight-edit step — the user just
  // entered the per-portion macros).
  const handleProductCreated = useCallback((food: QuickAddFoodOut) => {
    setPendingItems([
      {
        food_name: food.food_name,
        amount: food.amount,
        unit: food.unit,
        weight_g: food.weight_g,
        kcal: food.kcal,
        protein_g: food.protein_g,
        fat_g: food.fat_g,
        carbs_g: food.carbs_g,
        food_id: food.food_id,
      },
    ]);
    setFoodFormOpen(false);
    setMealPickerOpen(true);
  }, []);

  const handleSaveMeal = useCallback(
    async (mealType: MealType) => {
      if (savingMeal || pendingItems.length === 0) return;
      setSavingMeal(true);
      try {
        await api.bulkAddMeal({ meal_type: mealType, items: pendingItems });
        setToast(`✅ ${pendingItems.length} позиц. записаны`);
        setPendingItems([]);
        setMealPickerOpen(false);
        await load(date);
      } catch (e) {
        setToast(`⚠️ ${(e as Error).message}`);
      } finally {
        setSavingMeal(false);
        setTimeout(() => setToast(null), 2400);
      }
    },
    [savingMeal, pendingItems, load, date],
  );

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
            onClick={() => setActionSheetOpen(true)}
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

      <FabActionSheet
        open={actionSheetOpen}
        onClose={() => setActionSheetOpen(false)}
        onPickManual={() => {
          setActionSheetOpen(false);
          setFoodFormOpen(true);
        }}
        onPhotoResolved={handlePhotoResolved}
        onError={(msg) => {
          setToast(msg);
          setTimeout(() => setToast(null), 3000);
        }}
      />

      <FoodForm
        open={foodFormOpen}
        onClose={() => setFoodFormOpen(false)}
        title="Ручное заполнение"
        onCreated={handleProductCreated}
      />

      <MealTypeSheet
        open={mealPickerOpen}
        onPick={handleSaveMeal}
        onClose={() => setMealPickerOpen(false)}
        saving={savingMeal}
        count={pendingItems.length}
        kcal={pendingItems.reduce((s, it) => s + it.kcal, 0)}
      />

      {toast && (
        <div
          className="fixed left-1/2 -translate-x-1/2 transform rounded-full px-4 py-2 text-sm shadow-lg"
          style={{
            background: "var(--accent)",
            color: "white",
            bottom: "calc(env(safe-area-inset-bottom, 0px) + 160px)",
            zIndex: 60,
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
