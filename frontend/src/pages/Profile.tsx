import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Info } from "lucide-react";
import { useEffect, useState } from "react";
import {
  Controller,
  useForm,
  type Control,
  type FieldError,
} from "react-hook-form";
import { BottomSheet } from "../components/BottomSheet";
import {
  NumberField,
  SelectField,
  Segmented,
  Toggle,
} from "../components/FormFields";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { meQuery } from "../queries";
import { profileFormSchema, type ProfileFormValues } from "../schemas/profile";
import { greetingName } from "../telegram";
import type {
  ActivityLevel,
  Goal,
  ProfileUpdate,
  Sex,
  UserProfile,
} from "../types";

const ACTIVITY_OPTS: { v: ActivityLevel; label: string }[] = [
  { v: "sedentary", label: "Сидячий (мало движения)" },
  { v: "light", label: "Лёгкая (1–3 трен./нед)" },
  { v: "moderate", label: "Умеренная (3–5 трен./нед)" },
  { v: "active", label: "Высокая (6–7 трен./нед)" },
  { v: "very_active", label: "Очень высокая (физ. труд)" },
];

const GOAL_OPTS: { v: Goal; label: string }[] = [
  { v: "lose", label: "📉 Похудеть" },
  { v: "maintain", label: "⚖️ Поддерживать вес" },
  { v: "gain", label: "📈 Набрать вес" },
];

const SEX_OPTS: { v: Sex; label: string }[] = [
  { v: "male", label: "👨 Мужской" },
  { v: "female", label: "👩 Женский" },
];

const DEFAULT_VALUES: ProfileFormValues = {
  sex: "male",
  weight_kg: 70,
  height_cm: 175,
  age: 30,
  activity: "moderate",
  goal: "maintain",
  target_weight_kg: null,
  manual_targets: false,
  target_kcal: null,
  target_protein_g: null,
  target_fat_g: null,
  target_carbs_g: null,
};

function profileToForm(p: UserProfile): ProfileFormValues {
  return {
    sex: p.sex ?? "male",
    weight_kg: p.weight_kg ?? 70,
    height_cm: p.height_cm ?? 175,
    age: p.age ?? 30,
    activity: p.activity ?? "moderate",
    goal: p.goal ?? "maintain",
    target_weight_kg: p.target_weight_kg ?? null,
    manual_targets: false,
    target_kcal: p.targets.kcal ?? null,
    target_protein_g: p.targets.protein_g ?? null,
    target_fat_g: p.targets.fat_g ?? null,
    target_carbs_g: p.targets.carbs_g ?? null,
  };
}

export function Profile() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: profile } = useQuery(meQuery());
  const [formulaOpen, setFormulaOpen] = useState(false);
  const [saved, setSaved] = useState(false);

  const {
    register,
    control,
    handleSubmit,
    watch,
    reset,
    formState: { errors, isDirty },
  } = useForm<ProfileFormValues>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(profileFormSchema as any),
    defaultValues: DEFAULT_VALUES,
    mode: "onBlur",
  });

  const goal = watch("goal");
  const manualMode = watch("manual_targets");

  // Populate the form once the profile query resolves.
  useEffect(() => {
    if (profile) reset(profileToForm(profile));
    // reset is a stable ref — safe to omit
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  const updateMutation = useMutation({
    mutationFn: (payload: ProfileUpdate) => api.updateMe(payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(["me"], updated);
      reset(profileToForm(updated), { keepDefaultValues: false });
      toast.success("Сохранено", "Дневная норма обновлена");
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    },
    onError: (e) => {
      toast.error("Не удалось сохранить", (e as Error).message);
    },
  });

  const onSubmit = (values: ProfileFormValues) => {
    const payload: ProfileUpdate = {
      sex: values.sex,
      weight_kg: values.weight_kg,
      height_cm: values.height_cm,
      age: values.age,
      activity: values.activity,
      goal: values.goal,
      target_weight_kg:
        values.goal === "maintain" ? null : (values.target_weight_kg ?? null),
      manual_targets: values.manual_targets,
      target_kcal: values.manual_targets ? values.target_kcal : null,
      target_protein_g: values.manual_targets ? values.target_protein_g : null,
      target_fat_g: values.manual_targets ? values.target_fat_g : null,
      target_carbs_g: values.manual_targets ? values.target_carbs_g : null,
    };
    updateMutation.mutate(payload);
  };

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="mx-auto max-w-md px-4 pb-32 pt-16"
      noValidate
    >
      {/* Greeting + computed daily targets card. */}
      <div className="surface-card mb-4 p-5 shadow-sm">
        <div className="mb-1 text-sm text-tg-hint">Привет</div>
        <div className="mb-3 text-xl font-semibold text-tg-text">
          {greetingName()} 👋
        </div>

        {profile?.target_weight_kg &&
          profile.weight_kg &&
          profile.goal &&
          profile.goal !== "maintain" && (
            <div className="mb-3 flex items-center gap-2 rounded-xl bg-black/20 px-3 py-2 text-sm text-tg-text">
              <span>{profile.goal === "lose" ? "📉" : "📈"}</span>
              <span className="text-tg-hint">Цель:</span>
              <span className="font-medium">
                {profile.weight_kg}кг → {profile.target_weight_kg}кг
              </span>
              <span className="ml-auto text-xs text-tg-hint">
                {profile.target_weight_kg > profile.weight_kg ? "+" : ""}
                {(profile.target_weight_kg - profile.weight_kg).toFixed(1)} кг
              </span>
            </div>
          )}

        {profile?.targets.kcal ? (
          <div className="grid grid-cols-4 gap-2 text-center">
            {[
              ["🔥", profile.targets.kcal, "ккал"],
              ["🥩", profile.targets.protein_g, "Б"],
              ["🥑", profile.targets.fat_g, "Ж"],
              ["🍞", profile.targets.carbs_g, "У"],
            ].map(([icon, val, lbl]) => (
              <div key={lbl as string}>
                <div className="text-xl">{icon as string}</div>
                <div className="font-bold text-tg-text">{val as number}</div>
                <div className="text-xs text-tg-hint">{lbl as string}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-tg-hint">
            Заполни форму ниже, чтобы рассчитать дневную норму КБЖУ.
          </div>
        )}
      </div>

      {/* Form card — Mifflin-St Jeor inputs. */}
      <div className="surface-card mb-4 space-y-4 p-5 shadow-sm">
        <div className="text-sm font-semibold uppercase tracking-wide text-tg-hint">
          Параметры
        </div>

        <Controller
          control={control}
          name="sex"
          render={({ field }) => (
            <Segmented
              options={SEX_OPTS}
              value={field.value}
              onChange={field.onChange}
            />
          )}
        />

        <NumberField
          label="Вес, кг"
          name="weight_kg"
          register={register}
          error={errors.weight_kg}
        />
        <NumberField
          label="Рост, см"
          name="height_cm"
          register={register}
          error={errors.height_cm}
        />
        <NumberField
          label="Возраст"
          name="age"
          register={register}
          error={errors.age}
        />

        <SelectField
          label="Активность"
          name="activity"
          register={register}
          options={ACTIVITY_OPTS}
          error={errors.activity}
        />

        <SelectField
          label="Цель"
          name="goal"
          register={register}
          options={GOAL_OPTS}
          error={errors.goal}
        />

        {goal !== "maintain" && (
          <NumberField
            label={
              goal === "lose"
                ? "Целевой вес, кг (хочу похудеть до)"
                : "Целевой вес, кг (хочу набрать до)"
            }
            name="target_weight_kg"
            register={register}
            error={errors.target_weight_kg as FieldError | undefined}
          />
        )}
      </div>

      {/* Manual targets card. */}
      <div className="surface-card mb-4 p-5 shadow-sm">
        <Controller
          control={control}
          name="manual_targets"
          render={({ field }) => (
            <button
              type="button"
              onClick={() => field.onChange(!field.value)}
              className="flex w-full items-center justify-between gap-3"
              aria-pressed={field.value}
            >
              <div className="text-left">
                <div className="text-sm font-semibold text-tg-text">
                  Задать РСК и КБЖУ вручную
                </div>
                <div className="mt-0.5 text-xs text-tg-hint">
                  Игнорировать авто-расчёт по формуле
                </div>
              </div>
              <Toggle on={field.value} />
            </button>
          )}
        />

        {manualMode && (
          <div className="mt-4 grid grid-cols-2 gap-3">
            <NumberField
              label="Калории, ккал"
              name="target_kcal"
              register={register}
              error={errors.target_kcal as FieldError | undefined}
            />
            <NumberField
              label="Белки, г"
              name="target_protein_g"
              register={register}
              error={errors.target_protein_g as FieldError | undefined}
            />
            <NumberField
              label="Жиры, г"
              name="target_fat_g"
              register={register}
              error={errors.target_fat_g as FieldError | undefined}
            />
            <NumberField
              label="Углеводы, г"
              name="target_carbs_g"
              register={register}
              error={errors.target_carbs_g as FieldError | undefined}
            />
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => setFormulaOpen(true)}
        className="mb-3 flex w-full items-center justify-center gap-1.5 text-xs text-tg-hint transition active:opacity-70"
      >
        Расчёт по Mifflin-St Jeor
        <Info size={14} aria-hidden="true" />
      </button>

      <button
        type="submit"
        disabled={updateMutation.isPending || !isDirty}
        className="liquid-glass flex w-full items-center justify-center gap-2 rounded-2xl px-4 py-3.5 text-base font-semibold text-white transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          background: saved
            ? "linear-gradient(135deg, #22c55e, #16a34a)"
            : "linear-gradient(135deg, var(--accent), rgba(140,100,240,0.95))",
        }}
      >
        {saved && <Check size={18} />}
        {updateMutation.isPending
          ? "Сохраняю…"
          : saved
            ? "Сохранено"
            : manualMode
              ? "Сохранить ручные значения"
              : "Сохранить и пересчитать норму"}
      </button>

      {formulaOpen && <FormulaSheet onClose={() => setFormulaOpen(false)} />}
    </form>
  );
}

export type _ControlBoundary = Control<ProfileFormValues>;

function FormulaSheet({ onClose }: { onClose: () => void }) {
  return (
    <BottomSheet open onClose={onClose} title="Как считается норма">
      <div className="space-y-3 text-sm text-tg-text">
        <p>
          Дневная норма калорий (РСК) рассчитывается по формуле{" "}
          <b>Mifflin-St Jeor</b> — самой точной для здоровых взрослых.
        </p>

        <div className="rounded-xl border border-[var(--glass-stroke)] bg-black/20 p-3 font-mono text-[13px] leading-relaxed text-tg-text">
          <div>
            <span className="text-tg-hint">М:</span> BMR = 10·вес + 6.25·рост −
            5·возраст + 5
          </div>
          <div>
            <span className="text-tg-hint">Ж:</span> BMR = 10·вес + 6.25·рост −
            5·возраст − 161
          </div>
          <div className="mt-2">
            <span className="text-tg-hint">TDEE</span> = BMR · коэф. активности
          </div>
        </div>

        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-tg-hint">
            Коэффициенты активности
          </div>
          <ul className="space-y-1 text-[13px]">
            <li>Сидячий — ×1.2</li>
            <li>Лёгкая активность — ×1.375</li>
            <li>Умеренная — ×1.55</li>
            <li>Высокая — ×1.725</li>
            <li>Очень высокая — ×1.9</li>
          </ul>
        </div>

        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-tg-hint">
            Поправка под цель
          </div>
          <ul className="space-y-1 text-[13px]">
            <li>📉 Похудеть — TDEE − 15%</li>
            <li>⚖️ Поддерживать — TDEE</li>
            <li>📈 Набрать — TDEE + 15%</li>
          </ul>
        </div>

        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-tg-hint">
            Распределение БЖУ
          </div>
          <p className="text-[13px]">
            Белки 30% · Жиры 25% · Углеводы 45% от РСК. Калорийность: 1 г белка
            = 4 ккал, 1 г жиров = 9 ккал, 1 г углеводов = 4 ккал.
          </p>
        </div>

        <p className="text-xs text-tg-hint">
          Формула — ориентир. Если знаешь свою норму точнее (анализы, тренер) —
          переключи «вручную» сверху и впиши свои числа.
        </p>
      </div>
    </BottomSheet>
  );
}
