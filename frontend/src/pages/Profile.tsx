import { zodResolver } from "@hookform/resolvers/zod";
import { Check, ChevronDown, Info, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Controller,
  useForm,
  type Control,
  type FieldError,
  type Path,
  type UseFormRegister,
} from "react-hook-form";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
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
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [formulaOpen, setFormulaOpen] = useState(false);
  const [saved, setSaved] = useState(false);

  const {
    register,
    control,
    handleSubmit,
    watch,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<ProfileFormValues>({
    // `as any` is the standard workaround for zod-resolver's strict generic
    // mismatch with z.object().superRefine() — the runtime contract is fine.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(profileFormSchema as any),
    defaultValues: DEFAULT_VALUES,
    mode: "onBlur",
  });

  const goal = watch("goal");
  const manualMode = watch("manual_targets");

  useEffect(() => {
    api
      .getMe()
      .then((p) => {
        setProfile(p);
        reset(profileToForm(p));
      })
      .catch(() => {
        // Suppressed for now — form just stays on DEFAULT_VALUES if the
        // backend can't load the profile.
      });
    // reset is a stable ref → safe to leave out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSubmit = async (values: ProfileFormValues) => {
    try {
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
        target_protein_g: values.manual_targets
          ? values.target_protein_g
          : null,
        target_fat_g: values.manual_targets ? values.target_fat_g : null,
        target_carbs_g: values.manual_targets ? values.target_carbs_g : null,
      };
      const updated = await api.updateMe(payload);
      setProfile(updated);
      reset(profileToForm(updated), { keepDefaultValues: false });
      toast.success("Сохранено", "Дневная норма обновлена");
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      toast.error("Не удалось сохранить", (e as Error).message);
    }
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

      {/* Manual targets card — Controller for the toggle, register for inputs. */}
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

      {/* Hint + info-trigger for the formula bottom-sheet. */}
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
        disabled={isSubmitting || !isDirty}
        className="liquid-glass flex w-full items-center justify-center gap-2 rounded-2xl px-4 py-3.5 text-base font-semibold text-white transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          background: saved
            ? "linear-gradient(135deg, #22c55e, #16a34a)"
            : "linear-gradient(135deg, var(--accent), rgba(140,100,240,0.95))",
        }}
      >
        {saved && <Check size={18} />}
        {isSubmitting
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

/* ───────── small styled primitives, themed with tg-* tokens ───────── */

interface NumberFieldProps {
  label: string;
  name: Path<ProfileFormValues>;
  register: UseFormRegister<ProfileFormValues>;
  error?: FieldError;
}

function NumberField({ label, name, register, error }: NumberFieldProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-tg-hint">{label}</span>
      <input
        type="number"
        inputMode="numeric"
        step="any"
        {...register(name, {
          // RHF reads <input> value as string by default; coerce to number
          // for the schema. Empty string → null so the resolver can apply
          // its conditional "required" rules per cross-field validation.
          setValueAs: (v) => (v === "" || v == null ? null : Number(v)),
        })}
        className="w-full rounded-xl border border-[var(--glass-stroke)] bg-black/20 px-3.5 py-2.5 text-base text-tg-text outline-none transition focus:border-[var(--accent)]"
      />
      {error && (
        <span className="mt-1 block text-xs text-red-400">{error.message}</span>
      )}
    </label>
  );
}

interface SelectFieldProps {
  label: string;
  name: Path<ProfileFormValues>;
  register: UseFormRegister<ProfileFormValues>;
  options: { v: string; label: string }[];
  error?: FieldError;
}

function SelectField({
  label,
  name,
  register,
  options,
  error,
}: SelectFieldProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-tg-hint">{label}</span>
      <div className="relative">
        <select
          {...register(name)}
          className="w-full appearance-none rounded-xl border border-[var(--glass-stroke)] bg-black/20 px-3.5 py-2.5 pr-10 text-base text-tg-text outline-none transition focus:border-[var(--accent)]"
        >
          {options.map((o) => (
            <option key={o.v} value={o.v}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-tg-hint"
        />
      </div>
      {error && (
        <span className="mt-1 block text-xs text-red-400">{error.message}</span>
      )}
    </label>
  );
}

interface SegmentedProps<T extends string> {
  options: { v: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: SegmentedProps<T>) {
  return (
    <div className="grid grid-flow-col auto-cols-fr gap-1 rounded-xl border border-[var(--glass-stroke)] bg-black/20 p-1">
      {options.map((o) => {
        const selected = value === o.v;
        return (
          <button
            key={o.v}
            type="button"
            onClick={() => onChange(o.v)}
            className="rounded-lg px-2 py-2 text-sm font-medium transition"
            style={{
              color: selected ? "#ffffff" : "var(--tg-hint)",
              background: selected ? "var(--accent)" : "transparent",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Toggle({ on }: { on: boolean }) {
  return (
    <span
      role="presentation"
      className="relative inline-block h-7 w-12 shrink-0 rounded-full transition"
      style={{
        // iOS-style neutral grey for the off state — readable on both light
        // and dark Telegram themes (white-on-light was invisible before).
        background: on ? "var(--accent)" : "rgba(120, 120, 128, 0.32)",
      }}
    >
      <span
        className="absolute top-0.5 h-6 w-6 rounded-full bg-white transition-all"
        style={{
          left: on ? "22px" : "2px",
          boxShadow: "0 2px 4px rgba(0, 0, 0, 0.25)",
        }}
      />
    </span>
  );
}

// `control` is intentionally untyped at the boundary; consumers above already
// type their own Controller renders. Re-export only what page-level needs.
export type _ControlBoundary = Control<ProfileFormValues>;

/* ───────── Mifflin-St Jeor explainer — bottom sheet ───────── */

function FormulaSheet({ onClose }: { onClose: () => void }) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{
    startY: number;
    startT: number;
    active: boolean;
  } | null>(null);
  const [closing, setClosing] = useState(false);
  const offsetRef = useRef(0);

  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const applyOffset = (y: number) => {
    offsetRef.current = y;
    if (sheetRef.current) {
      sheetRef.current.style.transform = `translateY(${y}px)`;
    }
  };

  const close = () => {
    setClosing(true);
    window.setTimeout(onClose, 200);
  };

  const onDragStart = (e: React.PointerEvent<HTMLDivElement>) => {
    drag.current = {
      startY: e.clientY,
      startT: performance.now(),
      active: true,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    if (sheetRef.current) sheetRef.current.style.transition = "none";
  };

  const onDragMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current?.active) return;
    const dy = e.clientY - drag.current.startY;
    applyOffset(Math.max(0, dy));
  };

  const onDragEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current?.active) return;
    const dy = offsetRef.current;
    const dt = performance.now() - drag.current.startT;
    const velocity = dy / Math.max(dt, 1);
    drag.current.active = false;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* pointer already gone */
    }
    if (dy > 120 || velocity > 0.6) {
      close();
      return;
    }
    if (sheetRef.current) {
      sheetRef.current.style.transition =
        "transform 220ms cubic-bezier(0.32, 0.72, 0.24, 1)";
    }
    applyOffset(0);
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center">
      <button
        type="button"
        onClick={close}
        aria-label="Закрыть"
        className={`absolute inset-0 bg-black/60 backdrop-blur-sm ${
          closing ? "animate-sheet-fade-out" : "animate-sheet-fade"
        }`}
      />

      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label="Формула расчёта"
        className={`liquid-glass relative flex max-h-[85vh] w-full max-w-md flex-col rounded-t-3xl pt-3 ${
          closing ? "animate-sheet-slide-out" : "animate-sheet-slide"
        }`}
        style={{ marginTop: "max(env(safe-area-inset-top), 24px)" }}
      >
        <div
          className="px-5"
          style={{ touchAction: "none", cursor: "grab" }}
          onPointerDown={onDragStart}
          onPointerMove={onDragMove}
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
        >
          <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-white/30" />
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-tg-text">
              Как считается норма
            </h2>
            <button
              onClick={close}
              aria-label="Закрыть"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-white/5 text-tg-hint transition active:scale-90"
              style={{ touchAction: "auto" }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div
          className="space-y-3 overflow-y-auto px-5 pb-[calc(env(safe-area-inset-bottom)+24px)] text-sm text-tg-text"
          style={{ WebkitOverflowScrolling: "touch" }}
        >
          <p>
            Дневная норма калорий (РСК) рассчитывается по формуле{" "}
            <b>Mifflin-St Jeor</b> — самой точной для здоровых взрослых.
          </p>

          <div className="rounded-xl border border-[var(--glass-stroke)] bg-black/20 p-3 font-mono text-[13px] leading-relaxed text-tg-text">
            <div>
              <span className="text-tg-hint">М:</span> BMR = 10·вес + 6.25·рост
              − 5·возраст + 5
            </div>
            <div>
              <span className="text-tg-hint">Ж:</span> BMR = 10·вес + 6.25·рост
              − 5·возраст − 161
            </div>
            <div className="mt-2">
              <span className="text-tg-hint">TDEE</span> = BMR · коэф.
              активности
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
              Белки 30% · Жиры 25% · Углеводы 45% от РСК. Калорийность: 1 г
              белка = 4 ккал, 1 г жиров = 9 ккал, 1 г углеводов = 4 ккал.
            </p>
          </div>

          <p className="text-xs text-tg-hint">
            Формула — ориентир. Если знаешь свою норму точнее (анализы, тренер)
            — переключи «вручную» сверху и впиши свои числа.
          </p>
        </div>
      </div>
    </div>
  );
}
