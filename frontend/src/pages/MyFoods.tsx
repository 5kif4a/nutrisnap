import { Plus, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { MealType, QuickAddFoodOut } from "../types";

type FoodsTab = "search" | "recent" | "frequent";

const MEAL_TYPES: { v: MealType; label: string }[] = [
  { v: "breakfast", label: "Завтрак" },
  { v: "lunch", label: "Обед" },
  { v: "dinner", label: "Ужин" },
  { v: "snack", label: "Перекус" },
];

const TABS: { v: FoodsTab; label: string }[] = [
  { v: "search", label: "Поиск" },
  { v: "recent", label: "Недавно" },
  { v: "frequent", label: "Часто" },
];

function inferMealTypeByClock(): MealType {
  const h = new Date().getHours();
  if (h >= 6 && h < 11) return "breakfast";
  if (h >= 11 && h < 16) return "lunch";
  if (h >= 16 && h < 22) return "dinner";
  return "snack";
}

export function MyFoods() {
  const [mealType, setMealType] = useState<MealType>(inferMealTypeByClock());
  const [tab, setTab] = useState<FoodsTab>("recent");
  const [recent, setRecent] = useState<QuickAddFoodOut[]>([]);
  const [frequent, setFrequent] = useState<QuickAddFoodOut[]>([]);
  const [searchResults, setSearchResults] = useState<QuickAddFoodOut[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Recent + frequent: load whenever the meal_type changes.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [rec, freq] = await Promise.all([
          api.getRecentFoods({ mealType, limit: 20 }),
          api.getFrequentFoods({ mealType, limit: 20 }),
        ]);
        if (cancelled) return;
        setRecent(rec);
        // De-dup recents that also appear in frequent.
        const freqNames = new Set(freq.map((f) => f.food_name.toLowerCase()));
        setRecent(rec.filter((r) => !freqNames.has(r.food_name.toLowerCase())));
        setFrequent(freq);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [mealType]);

  // Search: debounced on the query input.
  useEffect(() => {
    if (tab !== "search") return;
    const q = searchQuery.trim();
    if (q.length < 2) {
      setSearchResults([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const rows = await api.searchFoods({ q, limit: 25 });
        if (!cancelled) setSearchResults(rows);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [searchQuery, tab]);

  const handleLog = useCallback(
    async (food: QuickAddFoodOut) => {
      if (busyName) return;
      setBusyName(food.food_name);
      try {
        await api.quickAddMeal({
          food_name: food.food_name,
          amount: food.amount,
          unit: food.unit,
          weight_g: food.weight_g,
          kcal: food.kcal,
          protein_g: food.protein_g,
          fat_g: food.fat_g,
          carbs_g: food.carbs_g,
          food_id: food.food_id,
          meal_type: mealType,
        });
        const mealLabel = MEAL_TYPES.find((m) => m.v === mealType)?.label ?? "";
        setToast(`✅ «${food.food_name}» → ${mealLabel}`);
        setTimeout(() => setToast(null), 2200);
        // Refresh recents/frequents so the just-logged item floats up.
        if (tab !== "search") {
          const [rec, freq] = await Promise.all([
            api.getRecentFoods({ mealType, limit: 20 }),
            api.getFrequentFoods({ mealType, limit: 20 }),
          ]);
          const freqNames = new Set(freq.map((f) => f.food_name.toLowerCase()));
          setRecent(rec.filter((r) => !freqNames.has(r.food_name.toLowerCase())));
          setFrequent(freq);
        }
      } catch (e) {
        setToast(`⚠️ ${(e as Error).message}`);
        setTimeout(() => setToast(null), 4000);
      } finally {
        setBusyName(null);
      }
    },
    [busyName, mealType, tab],
  );

  const visibleList = useMemo<QuickAddFoodOut[]>(() => {
    if (tab === "search") return searchResults;
    if (tab === "recent") return recent;
    return frequent;
  }, [tab, searchResults, recent, frequent]);

  const emptyMessage = useMemo(() => {
    if (loading) return null;
    if (tab === "search") {
      return searchQuery.trim().length < 2
        ? "Начни вводить название — найду в каталоге"
        : "Ничего не нашёл по этому запросу";
    }
    if (tab === "recent") {
      return "Здесь будут последние добавления для этого приёма";
    }
    return "Здесь будут продукты, которые ты ешь чаще всего";
  }, [tab, loading, searchQuery]);

  return (
    <div className="mx-auto max-w-md px-4 pb-32 pt-4">
      {/* Header — meal-type selector. Right padding keeps the global gear icon free. */}
      <div className="mb-3 pr-12">
        <div className="flex gap-1.5 overflow-x-auto rounded-2xl bg-tg-card p-1 shadow-sm">
          {MEAL_TYPES.map((m) => {
            const selected = mealType === m.v;
            return (
              <button
                key={m.v}
                onClick={() => setMealType(m.v)}
                className="flex-1 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium transition active:scale-95"
                style={{
                  color: selected ? "white" : "var(--tg-hint)",
                  background: selected ? "var(--accent)" : "transparent",
                }}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Three-tab switcher — FatSecret style. */}
      <div className="mb-3 flex border-b border-tg-card">
        {TABS.map((t) => {
          const selected = tab === t.v;
          return (
            <button
              key={t.v}
              onClick={() => setTab(t.v)}
              className="relative flex-1 px-2 py-3 text-sm font-medium transition"
              style={{
                color: selected ? "var(--accent)" : "var(--tg-hint)",
              }}
            >
              {t.label}
              {selected && (
                <span
                  className="absolute inset-x-2 bottom-0 h-0.5 rounded-full"
                  style={{ background: "var(--accent)" }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Search input — only on the search tab. */}
      {tab === "search" && (
        <div className="mb-3 flex items-center gap-2 rounded-2xl bg-tg-card px-3 py-2 shadow-sm">
          <Search size={18} className="shrink-0 text-tg-hint" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Поиск продукта"
            className="flex-1 bg-transparent text-sm text-tg-text outline-none placeholder:text-tg-hint"
            autoFocus
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              aria-label="Очистить"
              className="shrink-0 text-tg-hint active:scale-90"
            >
              <X size={18} />
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="mb-3 rounded-xl bg-red-100 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading && visibleList.length === 0 ? (
        <div className="py-20 text-center text-sm text-tg-hint">Загрузка…</div>
      ) : visibleList.length === 0 ? (
        <div className="rounded-2xl bg-tg-card p-6 text-center text-sm text-tg-hint">
          {emptyMessage}
        </div>
      ) : (
        <ul className="space-y-2">
          {visibleList.map((food, idx) => (
            <FoodRow
              key={`${food.food_id ?? "no-id"}-${food.food_name}-${idx}`}
              food={food}
              onAdd={handleLog}
              busy={busyName === food.food_name}
              showFrequency={tab === "frequent"}
            />
          ))}
        </ul>
      )}

      {toast && (
        <div
          className="fixed left-1/2 -translate-x-1/2 transform rounded-full px-4 py-2 text-sm shadow-lg"
          style={{
            background: "var(--accent)",
            color: "white",
            bottom: "calc(env(safe-area-inset-bottom, 0px) + 96px)",
            zIndex: 60,
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}

interface RowProps {
  food: QuickAddFoodOut;
  onAdd: (food: QuickAddFoodOut) => void;
  busy: boolean;
  showFrequency?: boolean;
}

function FoodRow({ food, onAdd, busy, showFrequency }: RowProps) {
  const portion = `${food.amount.toLocaleString("ru")} ${food.unit}`;
  const macros = `Б ${Math.round(food.protein_g)} · Ж ${Math.round(food.fat_g)} · У ${Math.round(food.carbs_g)}`;
  const freqBadge =
    showFrequency && food.frequency > 1 ? ` · ×${food.frequency}` : "";

  return (
    <li>
      <button
        onClick={() => onAdd(food)}
        disabled={busy}
        className="flex w-full items-center gap-3 rounded-2xl bg-tg-card px-4 py-3 text-left shadow-sm transition active:scale-[0.99] disabled:opacity-60"
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-medium text-tg-text">
            {food.food_name}
          </div>
          <div className="mt-0.5 text-xs text-tg-hint">
            {portion} · {Math.round(food.kcal)} ккал · {macros}
            {freqBadge}
          </div>
        </div>
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{
            background: busy ? "transparent" : "var(--accent-soft)",
            color: "var(--accent)",
          }}
        >
          {busy ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-tg-hint border-t-transparent" />
          ) : (
            <Plus size={18} />
          )}
        </span>
      </button>
    </li>
  );
}
