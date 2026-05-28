import { Check, Plus, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FoodForm } from "../components/FoodForm";
import { MealTypeSheet } from "../components/MealTypeSheet";
import { api } from "../lib/api";
import type {
  BulkAddItem,
  FoodMetric,
  MealType,
  QuickAddFoodOut,
} from "../types";

type FoodsTab = "search" | "recent" | "frequent";

const MEAL_TYPE_LABELS: Record<MealType, string> = {
  breakfast: "Завтрак",
  lunch: "Обед",
  dinner: "Ужин",
  snack: "Перекус",
};

const TABS: { v: FoodsTab; label: string }[] = [
  { v: "search", label: "Поиск" },
  { v: "recent", label: "Недавно" },
  { v: "frequent", label: "Часто" },
];

const UNIT_SHORT: Record<FoodMetric, string> = {
  g: "г",
  ml: "мл",
  piece: "шт",
  serving: "порц",
};

/** A food in the selection basket: original food + user-edited amount. */
interface SelectedItem {
  key: string;
  food: QuickAddFoodOut;
  amount: number;
}

/** Stable key for matching basket items against list rows. */
function keyFor(food: QuickAddFoodOut): string {
  return food.food_id ?? `name:${food.food_name}`;
}

/** Scale a food row's macros to the user-edited portion. */
function scale(food: QuickAddFoodOut, newAmount: number) {
  const factor = food.amount > 0 ? newAmount / food.amount : 0;
  return {
    weight_g: food.weight_g * factor,
    kcal: food.kcal * factor,
    protein_g: food.protein_g * factor,
    fat_g: food.fat_g * factor,
    carbs_g: food.carbs_g * factor,
  };
}

export function MyFoods() {
  const [tab, setTab] = useState<FoodsTab>("recent");
  const [recent, setRecent] = useState<QuickAddFoodOut[]>([]);
  const [frequent, setFrequent] = useState<QuickAddFoodOut[]>([]);
  const [searchResults, setSearchResults] = useState<QuickAddFoodOut[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [selection, setSelection] = useState<Map<string, SelectedItem>>(
    () => new Map(),
  );
  const [mealPickerOpen, setMealPickerOpen] = useState(false);
  const [foodFormOpen, setFoodFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const reloadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const [rec, freq] = await Promise.all([
        api.getRecentFoods({ limit: 20 }),
        api.getFrequentFoods({ limit: 20 }),
      ]);
      const freqNames = new Set(freq.map((f) => f.food_name.toLowerCase()));
      setRecent(rec.filter((r) => !freqNames.has(r.food_name.toLowerCase())));
      setFrequent(freq);
    } catch {
      setRecent([]);
      setFrequent([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + after every successful bulk save.
  useEffect(() => {
    void reloadHistory();
  }, [reloadHistory]);

  // Debounced catalog search on the search tab.
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
      try {
        const rows = await api.searchFoods({ q, limit: 25 });
        if (!cancelled) setSearchResults(rows);
      } catch {
        if (!cancelled) setSearchResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [searchQuery, tab]);

  const toggleSelect = useCallback((food: QuickAddFoodOut) => {
    setSelection((prev) => {
      const next = new Map(prev);
      const k = keyFor(food);
      if (next.has(k)) {
        next.delete(k);
      } else {
        next.set(k, { key: k, food, amount: food.amount });
      }
      return next;
    });
  }, []);

  const updateAmount = useCallback((key: string, amount: number) => {
    setSelection((prev) => {
      const cur = prev.get(key);
      if (!cur) return prev;
      const next = new Map(prev);
      next.set(key, { ...cur, amount: Number.isFinite(amount) ? amount : 0 });
      return next;
    });
  }, []);

  const removeFromSelection = useCallback((key: string) => {
    setSelection((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Map(prev);
      next.delete(key);
      return next;
    });
  }, []);

  const totals = useMemo(() => {
    let kcal = 0;
    for (const s of selection.values()) {
      if (s.amount > 0) kcal += scale(s.food, s.amount).kcal;
    }
    return { count: selection.size, kcal };
  }, [selection]);

  const handleSave = useCallback(
    async (mealType: MealType) => {
      if (saving) return;
      const items: BulkAddItem[] = [];
      for (const s of selection.values()) {
        if (s.amount <= 0) continue;
        const scaled = scale(s.food, s.amount);
        items.push({
          food_name: s.food.food_name,
          amount: s.amount,
          unit: s.food.unit,
          weight_g: scaled.weight_g,
          kcal: scaled.kcal,
          protein_g: scaled.protein_g,
          fat_g: scaled.fat_g,
          carbs_g: scaled.carbs_g,
          food_id: s.food.food_id,
        });
      }
      if (items.length === 0) {
        setMealPickerOpen(false);
        return;
      }
      setSaving(true);
      try {
        await api.bulkAddMeal({ meal_type: mealType, items });
        setToast(`✅ ${items.length} позиц. → ${MEAL_TYPE_LABELS[mealType]}`);
        setSelection(new Map());
        setMealPickerOpen(false);
        await reloadHistory();
      } catch (e) {
        setToast(`⚠️ ${(e as Error).message}`);
      } finally {
        setSaving(false);
        setTimeout(() => setToast(null), 2400);
      }
    },
    [saving, selection, reloadHistory],
  );

  const handleProductCreated = useCallback((food: QuickAddFoodOut) => {
    setFoodFormOpen(false);
    setSelection((prev) => {
      const next = new Map(prev);
      const k = keyFor(food);
      next.set(k, { key: k, food, amount: food.amount });
      return next;
    });
    setToast(`✅ Создан «${food.food_name}» — добавлен в корзину`);
    setTimeout(() => setToast(null), 2400);
  }, []);

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
      return "Здесь будут последние добавления";
    }
    return "Здесь будут продукты, которые ты ешь чаще всего";
  }, [tab, loading, searchQuery]);

  return (
    <div
      className="mx-auto max-w-md px-4 pt-16"
      style={{
        // Reserve room at the bottom for the basket bar + nav, otherwise the
        // last row hides under them.
        paddingBottom: selection.size > 0 ? 180 : 128,
      }}
    >
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

      {tab === "search" && (
        <>
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
          <button
            type="button"
            onClick={() => setFoodFormOpen(true)}
            className="mb-3 flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-[var(--glass-stroke)] bg-transparent px-3 py-2.5 text-sm font-medium text-tg-hint transition active:scale-[0.99]"
          >
            <Plus size={16} />
            Создать продукт
          </button>
        </>
      )}

      {loading && visibleList.length === 0 ? (
        <div className="py-20 text-center text-sm text-tg-hint">Загрузка…</div>
      ) : visibleList.length === 0 ? (
        <div className="rounded-2xl bg-tg-card p-6 text-center text-sm text-tg-hint">
          {emptyMessage}
        </div>
      ) : (
        <ul className="space-y-2">
          {visibleList.map((food, idx) => {
            const k = keyFor(food);
            const sel = selection.get(k);
            return (
              <FoodRow
                key={`${k}-${idx}`}
                food={food}
                selected={sel}
                onToggle={() => toggleSelect(food)}
                onAmountChange={(v) => updateAmount(k, v)}
                onRemove={() => removeFromSelection(k)}
                showFrequency={tab === "frequent"}
              />
            );
          })}
        </ul>
      )}

      {/* Basket bar — visible when something is selected. */}
      {selection.size > 0 && !mealPickerOpen && (
        <div
          className="pointer-events-none fixed inset-x-0 z-40"
          style={{
            bottom: "calc(env(safe-area-inset-bottom, 0px) + 88px)",
          }}
        >
          <div className="mx-auto flex max-w-md justify-end px-4">
            <button
              onClick={() => setMealPickerOpen(true)}
              className="liquid-glass pointer-events-auto flex items-center gap-3 rounded-full pl-4 pr-2 py-2 text-white shadow-lg active:scale-[0.98]"
              style={{
                background:
                  "linear-gradient(135deg, var(--accent), rgba(120,92,220,0.95))",
              }}
            >
              <span className="text-sm font-semibold">
                {totals.count} · {Math.round(totals.kcal)} ккал
              </span>
              <span className="flex h-9 items-center gap-1 rounded-full bg-white/20 px-3 text-sm font-semibold">
                Сохранить
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Meal-type picker sheet — shared with FabActionSheet. */}
      <MealTypeSheet
        open={mealPickerOpen}
        onPick={handleSave}
        onClose={() => setMealPickerOpen(false)}
        saving={saving}
        count={totals.count}
        kcal={totals.kcal}
      />

      <FoodForm
        open={foodFormOpen}
        onClose={() => setFoodFormOpen(false)}
        title="Создать продукт"
        onCreated={handleProductCreated}
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

interface RowProps {
  food: QuickAddFoodOut;
  selected: SelectedItem | undefined;
  onToggle: () => void;
  onAmountChange: (v: number) => void;
  onRemove: () => void;
  showFrequency?: boolean;
}

function FoodRow({
  food,
  selected,
  onToggle,
  onAmountChange,
  onRemove,
  showFrequency,
}: RowProps) {
  const isSelected = selected !== undefined;
  const amount = selected?.amount ?? food.amount;
  const scaled = isSelected ? scale(food, amount) : null;

  const portion = `${food.amount.toLocaleString("ru")} ${UNIT_SHORT[food.unit]}`;
  const macros = `Б ${Math.round(food.protein_g)} · Ж ${Math.round(food.fat_g)} · У ${Math.round(food.carbs_g)}`;
  const freqBadge =
    showFrequency && food.frequency > 1 ? ` · ×${food.frequency}` : "";

  return (
    <li>
      <div
        className="rounded-2xl bg-tg-card shadow-sm transition"
        style={{
          outline: isSelected ? "2px solid var(--accent)" : "none",
        }}
      >
        <button
          onClick={onToggle}
          className="flex w-full items-center gap-3 px-4 py-3 text-left active:scale-[0.99]"
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
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition"
            style={{
              background: isSelected ? "var(--accent)" : "var(--accent-soft)",
              color: isSelected ? "white" : "var(--accent)",
            }}
          >
            <Check size={18} strokeWidth={2.5} />
          </span>
        </button>

        {isSelected && scaled && (
          <div className="border-t border-tg-border px-4 py-3">
            <div className="mb-2 flex items-center gap-2">
              <label className="flex-1 text-xs uppercase tracking-wide text-tg-hint">
                Сколько
              </label>
              <input
                type="number"
                inputMode="decimal"
                value={amount === 0 ? "" : amount}
                min={0}
                step={food.unit === "g" || food.unit === "ml" ? 10 : 1}
                onChange={(e) => onAmountChange(Number(e.target.value))}
                className="w-24 rounded-xl border border-[var(--glass-stroke)] bg-black/20 px-3 py-2 text-right text-base text-tg-text outline-none focus:border-[var(--accent)]"
              />
              <span className="w-10 text-sm text-tg-hint">
                {UNIT_SHORT[food.unit]}
              </span>
            </div>

            <div className="flex items-center justify-between gap-3">
              <div className="text-xs text-tg-hint">
                <span className="font-semibold text-tg-text">
                  {Math.round(scaled.kcal)} ккал
                </span>
                {" · "}Б {Math.round(scaled.protein_g)} · Ж{" "}
                {Math.round(scaled.fat_g)} · У {Math.round(scaled.carbs_g)}
              </div>
              <button
                onClick={onRemove}
                aria-label="Убрать"
                className="flex items-center gap-1 rounded-full bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 active:scale-95"
              >
                <Trash2 size={14} />
                Убрать
              </button>
            </div>
          </div>
        )}
      </div>
    </li>
  );
}
