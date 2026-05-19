import { useState } from "react";
import type { MealOut, MealType } from "../types";

const MEAL_LABELS: Record<MealType, string> = {
  breakfast: "🍳 Завтрак",
  lunch: "🍲 Обед",
  dinner: "🍝 Ужин",
  snack: "🍎 Перекус",
};

export function MealCard({ meal }: { meal: MealOut }) {
  const [open, setOpen] = useState(false);
  const time = new Date(meal.eaten_at).toLocaleTimeString("ru", {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="rounded-2xl bg-tg-card p-4 shadow-sm">
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
                  · {it.amount % 1 === 0 ? it.amount : it.amount.toFixed(1)}{" "}
                  {it.unit}
                </span>
              </span>
              <span className="text-tg-hint">{Math.round(it.kcal)} ккал</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
