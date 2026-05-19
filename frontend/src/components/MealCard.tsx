import { Trash2 } from "lucide-react";
import { useState } from "react";
import type { MealOut, MealType } from "../types";

const MEAL_LABELS: Record<MealType, string> = {
  breakfast: "🍳 Завтрак",
  lunch: "🍲 Обед",
  dinner: "🍝 Ужин",
  snack: "🍎 Перекус",
};

interface Props {
  meal: MealOut;
  onDelete: (id: string) => Promise<void> | void;
}

export function MealCard({ meal, onDelete }: Props) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const time = new Date(meal.eaten_at).toLocaleTimeString("ru", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (deleting) return;
    if (
      !window.confirm(`Удалить «${MEAL_LABELS[meal.meal_type]}» за ${time}?`)
    ) {
      return;
    }
    setDeleting(true);
    try {
      await onDelete(meal.id);
    } catch (err) {
      setDeleting(false);
      window.alert(`Не получилось удалить: ${(err as Error).message}`);
    }
  };

  return (
    <div
      className={`rounded-2xl bg-tg-card p-4 shadow-sm transition-opacity ${
        deleting ? "opacity-50" : ""
      }`}
    >
      <button
        className="flex w-full items-center justify-between"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="text-left">
          <div className="font-semibold text-tg-text">
            {MEAL_LABELS[meal.meal_type]}
          </div>
          <div className="text-xs text-tg-hint">
            {time} · {meal.items.length} поз.
          </div>
        </div>
        <div className="text-right">
          <div className="font-bold text-tg-text">
            {Math.round(meal.kcal)} ккал
          </div>
          <div className="text-xs text-tg-hint">
            Б {Math.round(meal.protein_g)} · Ж {Math.round(meal.fat_g)} · У{" "}
            {Math.round(meal.carbs_g)}
          </div>
        </div>
      </button>

      {open && (
        <>
          <ul className="mt-3 space-y-2 border-t border-tg-border pt-3">
            {meal.items.map((it) => (
              <li
                key={it.id}
                className="flex items-center justify-between text-sm"
              >
                <span className="text-tg-text">
                  {it.food_name}
                  <span className="text-tg-hint">
                    {" "}
                    · {it.amount % 1 === 0
                      ? it.amount
                      : it.amount.toFixed(1)}{" "}
                    {it.unit}
                  </span>
                </span>
                <span className="text-tg-hint">{Math.round(it.kcal)} ккал</span>
              </li>
            ))}
          </ul>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-red-500/10 px-3 py-2.5 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/15 active:bg-red-500/25 disabled:opacity-50"
          >
            <Trash2 size={16} strokeWidth={2.2} />
            Удалить приём
          </button>
        </>
      )}
    </div>
  );
}
