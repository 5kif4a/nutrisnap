import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { CircularProgress } from "../components/CircularProgress";
import { FabActionSheet } from "../components/FabActionSheet";
import { FoodForm } from "../components/FoodForm";
import { MacroBar } from "../components/MacroBar";
import { MealCard } from "../components/MealCard";
import { MealTypeSheet } from "../components/MealTypeSheet";
import { api } from "../lib/api";
import { humanDate, monthOf, todayISO, weekGrid } from "../lib/date";
import { dayQuery, monthQuery } from "../queries";
import type {
  BulkAddItem,
  DayResponse,
  DayStatus,
  MealType,
  QuickAddFoodOut,
  ResolvedItem,
} from "../types";

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

export function Dashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { date: searchDate } = useSearch({ from: "/dashboard" });
  const date = searchDate ?? todayISO();

  const { data, isLoading } = useQuery({
    ...dayQuery(date),
    placeholderData: emptyDay(date),
  });

  const [actionSheetOpen, setActionSheetOpen] = useState(false);
  const [foodFormOpen, setFoodFormOpen] = useState(false);
  const [pendingItems, setPendingItems] = useState<BulkAddItem[]>([]);
  const [mealPickerOpen, setMealPickerOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const week = useMemo(() => weekGrid(date), [date]);
  const weekMonths = useMemo(
    () => Array.from(new Set([monthOf(week[0]), monthOf(week[6])])),
    [week],
  );

  const monthResults = useQueries({
    queries: weekMonths.map((m) => monthQuery(m)),
  });

  // Each month result's data object is stable (same reference) until data
  // actually changes, so using them as deps gives correct memoisation.
  const m0 = monthResults[0]?.data;
  const m1 = monthResults[1]?.data;
  const weekStatus = useMemo(() => {
    const map = new Map<string, { status: DayStatus; kcal: number }>();
    for (const monthData of [m0, m1]) {
      if (monthData) {
        for (const d of monthData.days) map.set(d.date, d);
      }
    }
    return map;
  }, [m0, m1]);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteMeal(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["day", date] });
      void queryClient.invalidateQueries({ queryKey: ["month"] });
    },
  });

  const saveMealMutation = useMutation({
    mutationFn: (args: { mealType: MealType; items: BulkAddItem[] }) =>
      api.bulkAddMeal({ meal_type: args.mealType, items: args.items }),
    onSuccess: (_, { items }) => {
      void queryClient.invalidateQueries({ queryKey: ["day", date] });
      void queryClient.invalidateQueries({ queryKey: ["month"] });
      void queryClient.invalidateQueries({ queryKey: ["foods"] });
      setToast(`✅ ${items.length} позиц. записаны`);
      setPendingItems([]);
      setMealPickerOpen(false);
      setTimeout(() => setToast(null), 2400);
    },
    onError: (e) => {
      setToast(`⚠️ ${(e as Error).message}`);
      setTimeout(() => setToast(null), 2400);
    },
  });

  const today = todayISO();

  const handlePhotoResolved = (items: ResolvedItem[]) => {
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
  };

  const handleProductCreated = (food: QuickAddFoodOut) => {
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
  };

  const handleSaveMeal = (mealType: MealType) => {
    if (saveMealMutation.isPending || pendingItems.length === 0) return;
    saveMealMutation.mutate({ mealType, items: pendingItems });
  };

  return (
    <div className="mx-auto max-w-md px-4 pb-32 pt-16">
      {/* Selected day label. */}
      <div className="mb-2 text-center text-sm font-semibold text-tg-text">
        {humanDate(date)}
      </div>

      {/* Week strip — 7 cells Mon→Sun coloured by daily fill status. */}
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
              onClick={() =>
                void navigate({ to: "/dashboard", search: { date: iso } })
              }
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

      {isLoading && !data ? (
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
                <MealCard
                  key={m.id}
                  meal={m}
                  onDelete={(id) => deleteMutation.mutate(id)}
                />
              ))
            )}
          </div>
        </>
      ) : null}

      {/* FAB — sits above the liquid-glass nav. */}
      <div
        className="pointer-events-none fixed inset-x-0 z-40"
        style={{
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
        saving={saveMealMutation.isPending}
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
