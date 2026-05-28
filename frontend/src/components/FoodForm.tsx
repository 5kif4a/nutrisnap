import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useState } from "react";
import { z } from "zod";
import { BottomSheet } from "./BottomSheet";
import { NumberField, SelectField } from "./FormFields";
import { api } from "../lib/api";
import type {
  CreateCustomFoodRequest,
  FoodMetric,
  QuickAddFoodOut,
} from "../types";

/* ───────── FatSecret-style «create product» form. Same component is used
   for the FAB «Ручное заполнение» flow and the MyFoods «+ Создать продукт»
   flow — only the title and the post-save callback differ. ───────── */

const METRIC_OPTS: { v: FoodMetric; label: string }[] = [
  { v: "g", label: "100 граммов" },
  { v: "ml", label: "100 миллилитров" },
  { v: "piece", label: "1 штука" },
  { v: "serving", label: "1 порция" },
];

// Macros are stored per the metric's natural unit (per 100g/ml or per piece/
// serving). `piece_weight_g` is required only when the user picked piece or
// serving — that's the gram-equivalent used by daily-totals math.
const foodFormSchema = z
  .object({
    name: z.string().trim().min(1, "Назови продукт").max(255),
    brand: z
      .string()
      .trim()
      .max(128)
      .nullish()
      .transform((v) => (v ? v : null)),
    metric: z.enum(["g", "ml", "piece", "serving"]),
    kcal: z.number().min(0).max(2000),
    protein_g: z.number().min(0).max(200),
    fat_g: z.number().min(0).max(200),
    carbs_g: z.number().min(0).max(200),
    piece_weight_g: z.number().positive().max(2000).nullable().optional(),
  })
  .superRefine((data, ctx) => {
    if (
      (data.metric === "piece" || data.metric === "serving") &&
      (data.piece_weight_g == null || data.piece_weight_g <= 0)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["piece_weight_g"],
        message: "Укажи вес 1 штуки / порции в граммах",
      });
    }
  });

type FoodFormValues = z.infer<typeof foodFormSchema>;

interface Props {
  open: boolean;
  onClose: () => void;
  /** Heading shown in the sheet — e.g. «Создать продукт» / «Ручное заполнение». */
  title?: string;
  /** Called after the Food row is created in the catalog. The new food is
   *  already a QuickAddFoodOut with a default portion (per the metric), ready
   *  to drop into the meal-basket. */
  onCreated: (food: QuickAddFoodOut) => void;
}

const DEFAULT_VALUES: FoodFormValues = {
  name: "",
  brand: null,
  metric: "g",
  kcal: 0,
  protein_g: 0,
  fat_g: 0,
  carbs_g: 0,
  piece_weight_g: null,
};

export function FoodForm({
  open,
  onClose,
  title = "Создать продукт",
  onCreated,
}: Props) {
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FoodFormValues>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(foodFormSchema as any),
    defaultValues: DEFAULT_VALUES,
    mode: "onBlur",
  });

  const metric = watch("metric");
  const needsPieceWeight = metric === "piece" || metric === "serving";

  const onSubmit = async (values: FoodFormValues) => {
    setSubmitError(null);
    const payload: CreateCustomFoodRequest = {
      name: values.name,
      brand: values.brand ?? null,
      metric: values.metric,
      kcal: values.kcal,
      protein_g: values.protein_g,
      fat_g: values.fat_g,
      carbs_g: values.carbs_g,
      piece_weight_g: needsPieceWeight ? (values.piece_weight_g ?? null) : null,
    };
    try {
      const food = await api.createCustomFood(payload);
      reset(DEFAULT_VALUES);
      onCreated(food);
    } catch (e) {
      setSubmitError((e as Error).message);
    }
  };

  const close = () => {
    reset(DEFAULT_VALUES);
    setSubmitError(null);
    onClose();
  };

  // Macro labels switch their suffix between "на 100 г / мл" and "на 1 шт /
  // порц" so the user knows what scale they're entering.
  const perUnitSuffix =
    metric === "g"
      ? "на 100 г"
      : metric === "ml"
        ? "на 100 мл"
        : metric === "piece"
          ? "на 1 шт"
          : "на 1 порц";

  return (
    <BottomSheet open={open} onClose={close} title={title}>
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="space-y-4 pb-2"
        noValidate
      >
        {/* НАЗВАНИЕ */}
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1.5 block text-xs uppercase tracking-wide text-tg-hint">
              Название
            </span>
            <input
              type="text"
              {...register("name")}
              placeholder="Например, Гречка с курицей"
              className="w-full rounded-xl border border-[var(--glass-stroke)] bg-black/20 px-3.5 py-2.5 text-base text-tg-text outline-none transition focus:border-[var(--accent)]"
            />
            {errors.name && (
              <span className="mt-1 block text-xs text-red-400">
                {errors.name.message}
              </span>
            )}
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs uppercase tracking-wide text-tg-hint">
              Бренд (необязательно)
            </span>
            <input
              type="text"
              {...register("brand")}
              placeholder="Например, President"
              className="w-full rounded-xl border border-[var(--glass-stroke)] bg-black/20 px-3.5 py-2.5 text-base text-tg-text outline-none transition focus:border-[var(--accent)]"
            />
          </label>
        </div>

        {/* РАЗМЕР ПОРЦИИ */}
        <div className="space-y-3 rounded-2xl bg-black/10 p-3">
          <div className="text-xs uppercase tracking-wide text-tg-hint">
            Размер порции
          </div>
          <SelectField<FoodFormValues>
            label="Единица"
            name="metric"
            register={register}
            options={METRIC_OPTS.map((o) => ({ v: o.v, label: o.label }))}
            error={errors.metric as never}
          />
          {needsPieceWeight && (
            <NumberField<FoodFormValues>
              label="Вес 1 штуки / порции, г"
              name="piece_weight_g"
              register={register}
              error={errors.piece_weight_g}
              step={1}
            />
          )}
        </div>

        {/* ПИЩЕВАЯ ЦЕННОСТЬ */}
        <div className="space-y-3 rounded-2xl bg-black/10 p-3">
          <div className="text-xs uppercase tracking-wide text-tg-hint">
            Пищевая ценность · {perUnitSuffix}
          </div>
          <NumberField<FoodFormValues>
            label="Калории, ккал"
            name="kcal"
            register={register}
            error={errors.kcal}
            step={1}
          />
          <div className="grid grid-cols-3 gap-2">
            <NumberField<FoodFormValues>
              label="Белки, г"
              name="protein_g"
              register={register}
              error={errors.protein_g}
              step="any"
            />
            <NumberField<FoodFormValues>
              label="Жиры, г"
              name="fat_g"
              register={register}
              error={errors.fat_g}
              step="any"
            />
            <NumberField<FoodFormValues>
              label="Углеводы, г"
              name="carbs_g"
              register={register}
              error={errors.carbs_g}
              step="any"
            />
          </div>
        </div>

        {submitError && (
          <div className="rounded-xl bg-red-500/10 p-3 text-sm text-red-400">
            {submitError}
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="liquid-glass flex w-full items-center justify-center gap-2 rounded-2xl px-4 py-3.5 text-base font-semibold text-white transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            background:
              "linear-gradient(135deg, var(--accent), rgba(140,100,240,0.95))",
          }}
        >
          {isSubmitting ? "Сохраняю…" : "Сохранить продукт"}
        </button>
      </form>
    </BottomSheet>
  );
}
