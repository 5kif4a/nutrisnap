import { BottomSheet } from "./BottomSheet";
import type { MealType } from "../types";

/* ───────── Meal-type picker bottom-sheet. Shared between the MyFoods
   basket-save flow and the FAB action-sheet (camera / manual). ───────── */

const MEAL_TYPES: { v: MealType; label: string }[] = [
  { v: "breakfast", label: "Завтрак" },
  { v: "lunch", label: "Обед" },
  { v: "dinner", label: "Ужин" },
  { v: "snack", label: "Перекус" },
];

interface Props {
  open: boolean;
  onPick: (mealType: MealType) => void;
  onClose: () => void;
  saving?: boolean;
  count?: number;
  kcal?: number;
}

export function MealTypeSheet({
  open,
  onPick,
  onClose,
  saving = false,
  count,
  kcal,
}: Props) {
  const subtitle =
    count !== undefined
      ? `${count} позиц. · ${Math.round(kcal ?? 0)} ккал`
      : undefined;
  return (
    <BottomSheet open={open} onClose={onClose} title="Куда записать?">
      {subtitle && <div className="mb-4 text-xs text-tg-hint">{subtitle}</div>}

      <div className="grid grid-cols-2 gap-2 pb-2">
        {MEAL_TYPES.map((m) => (
          <button
            key={m.v}
            onClick={() => onPick(m.v)}
            disabled={saving}
            className="rounded-2xl px-4 py-4 text-base font-semibold text-white shadow-sm transition active:scale-[0.97] disabled:opacity-60"
            style={{
              background:
                "linear-gradient(135deg, var(--accent), rgba(120,92,220,0.95))",
            }}
          >
            {m.label}
          </button>
        ))}
      </div>
    </BottomSheet>
  );
}
