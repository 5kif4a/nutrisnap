import { ChevronRight } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { api } from "../lib/api";
import { greetingName } from "../telegram";
import type { ActivityLevel, Goal, ProfileUpdate, Sex } from "../types";

/* ───────── Story-style fullscreen onboarding shown when the user opens
   the Mini App before completing /start in the bot. Mirrors the bot
   ConversationHandler at backend/app/bot/handlers/onboard.py — the
   server-side TDEE/macro computation is reused via PUT /api/me. ───────── */

const ACTIVITY_OPTS: { v: ActivityLevel; label: string; hint: string }[] = [
  { v: "sedentary", label: "Сидячий", hint: "мало движения" },
  { v: "light", label: "Лёгкая", hint: "1–3 трен. в неделю" },
  { v: "moderate", label: "Умеренная", hint: "3–5 трен. в неделю" },
  { v: "active", label: "Высокая", hint: "6–7 трен. в неделю" },
  { v: "very_active", label: "Очень высокая", hint: "физ. труд" },
];

const GOAL_OPTS: { v: Goal; label: string; emoji: string }[] = [
  { v: "lose", label: "Похудеть", emoji: "📉" },
  { v: "maintain", label: "Поддерживать вес", emoji: "⚖️" },
  { v: "gain", label: "Набрать вес", emoji: "📈" },
];

interface FormState {
  sex: Sex | null;
  weight_kg: number | null;
  height_cm: number | null;
  age: number | null;
  activity: ActivityLevel | null;
  goal: Goal | null;
  target_weight_kg: number | null;
}

const INITIAL: FormState = {
  sex: null,
  weight_kg: null,
  height_cm: null,
  age: null,
  activity: null,
  goal: null,
  target_weight_kg: null,
};

interface Props {
  onComplete: () => void;
}

export function Onboarding({ onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Steps 0..5 are always present. Step 6 (target_weight) only when goal
  // is lose / gain — maintain skips it. The progress bar reflects that.
  const needsTargetWeight = form.goal === "lose" || form.goal === "gain";
  const totalSteps = needsTargetWeight ? 7 : 6;

  const isStepValid = useMemo(() => {
    switch (step) {
      case 0:
        return form.sex != null;
      case 1:
        return (
          form.weight_kg != null &&
          form.weight_kg >= 30 &&
          form.weight_kg <= 300
        );
      case 2:
        return (
          form.height_cm != null &&
          form.height_cm >= 100 &&
          form.height_cm <= 250
        );
      case 3:
        return form.age != null && form.age >= 10 && form.age <= 120;
      case 4:
        return form.activity != null;
      case 5:
        return form.goal != null;
      case 6:
        return (
          form.target_weight_kg != null &&
          form.target_weight_kg >= 30 &&
          form.target_weight_kg <= 300
        );
      default:
        return false;
    }
  }, [step, form]);

  const isFinalStep = step === totalSteps - 1;

  const goNext = useCallback(() => {
    if (!isStepValid || submitting) return;
    if (isFinalStep) {
      void submit();
      return;
    }
    setStep((s) => s + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStepValid, isFinalStep, submitting]);

  const goPrev = () => {
    if (submitting) return;
    setStep((s) => Math.max(0, s - 1));
  };

  const submit = async () => {
    if (
      form.sex == null ||
      form.weight_kg == null ||
      form.height_cm == null ||
      form.age == null ||
      form.activity == null ||
      form.goal == null
    ) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload: ProfileUpdate = {
        sex: form.sex,
        weight_kg: form.weight_kg,
        height_cm: form.height_cm,
        age: form.age,
        activity: form.activity,
        goal: form.goal,
        target_weight_kg:
          form.goal === "maintain" ? null : form.target_weight_kg,
      };
      await api.updateMe(payload);
      onComplete();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex flex-col"
      style={{
        background: "var(--tg-bg)",
        paddingTop: "max(env(safe-area-inset-top), 16px)",
        paddingBottom: "max(env(safe-area-inset-bottom), 16px)",
      }}
    >
      {/* Progress segments */}
      <div className="mx-auto flex w-full max-w-md gap-1 px-4">
        {Array.from({ length: totalSteps }).map((_, i) => (
          <span
            key={i}
            className="h-1 flex-1 rounded-full transition"
            style={{
              background:
                i < step
                  ? "var(--accent)"
                  : i === step
                    ? "var(--accent)"
                    : "rgba(255,255,255,0.15)",
              opacity: i <= step ? 1 : 0.4,
            }}
          />
        ))}
      </div>

      <div className="mx-auto flex w-full max-w-md flex-1 flex-col px-5 pt-8">
        <StepHeader step={step} totalSteps={totalSteps} />

        <div className="mt-6 flex-1 overflow-y-auto">
          {step === 0 && (
            <SexStep
              value={form.sex}
              onChange={(v) => setForm({ ...form, sex: v })}
            />
          )}
          {step === 1 && (
            <NumberStep
              label="Вес сейчас, кг"
              value={form.weight_kg}
              min={30}
              max={300}
              onChange={(v) => setForm({ ...form, weight_kg: v })}
            />
          )}
          {step === 2 && (
            <NumberStep
              label="Рост, см"
              value={form.height_cm}
              min={100}
              max={250}
              onChange={(v) => setForm({ ...form, height_cm: v })}
            />
          )}
          {step === 3 && (
            <NumberStep
              label="Возраст"
              value={form.age}
              min={10}
              max={120}
              onChange={(v) => setForm({ ...form, age: v })}
            />
          )}
          {step === 4 && (
            <CardChoiceStep
              options={ACTIVITY_OPTS.map((o) => ({
                v: o.v,
                title: o.label,
                subtitle: o.hint,
              }))}
              value={form.activity}
              onChange={(v) => setForm({ ...form, activity: v })}
            />
          )}
          {step === 5 && (
            <CardChoiceStep
              options={GOAL_OPTS.map((o) => ({
                v: o.v,
                title: `${o.emoji} ${o.label}`,
                subtitle: "",
              }))}
              value={form.goal}
              onChange={(v) => setForm({ ...form, goal: v })}
            />
          )}
          {step === 6 && (
            <NumberStep
              label={
                form.goal === "lose"
                  ? "Целевой вес — хочу похудеть до, кг"
                  : "Целевой вес — хочу набрать до, кг"
              }
              value={form.target_weight_kg}
              min={30}
              max={300}
              onChange={(v) => setForm({ ...form, target_weight_kg: v })}
            />
          )}
        </div>

        {error && (
          <div className="mb-2 rounded-xl bg-red-500/10 p-3 text-sm text-red-400">
            {error}
          </div>
        )}

        <div className="mt-4 flex items-center gap-3">
          {step > 0 && (
            <button
              type="button"
              onClick={goPrev}
              disabled={submitting}
              className="flex h-12 w-12 items-center justify-center rounded-full bg-tg-card text-tg-hint active:scale-95"
              aria-label="Назад"
            >
              <ChevronRight size={20} className="rotate-180" />
            </button>
          )}
          <button
            type="button"
            onClick={goNext}
            disabled={!isStepValid || submitting}
            className="liquid-glass flex h-12 flex-1 items-center justify-center gap-2 rounded-full px-4 text-base font-semibold text-white transition active:scale-[0.98] disabled:opacity-50"
            style={{
              background:
                "linear-gradient(135deg, var(--accent), rgba(140,100,240,0.95))",
            }}
          >
            {submitting ? "Считаю норму…" : isFinalStep ? "Готово" : "Далее"}
          </button>
        </div>
      </div>
    </div>
  );
}

function StepHeader({
  step,
  totalSteps,
}: {
  step: number;
  totalSteps: number;
}) {
  const titles = [
    "Привет 👋",
    "Сколько ты весишь?",
    "Какой у тебя рост?",
    "Сколько тебе лет?",
    "Уровень активности",
    "Твоя цель",
    "Целевой вес",
  ];
  const subtitles = [
    `${greetingName()}, давай настроим твою норму КБЖУ`,
    "Округли до целого, точнее не нужно",
    "В сантиметрах",
    "Это влияет на расчёт нормы",
    "Тренируешься в неделю",
    "Что хочешь от веса",
    "К чему стремишься",
  ];
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-tg-hint">
        Шаг {step + 1} из {totalSteps}
      </div>
      <div className="mt-1 text-2xl font-bold text-tg-text">{titles[step]}</div>
      <div className="mt-1 text-sm text-tg-hint">{subtitles[step]}</div>
    </div>
  );
}

function SexStep({
  value,
  onChange,
}: {
  value: Sex | null;
  onChange: (v: Sex) => void;
}) {
  const options: { v: Sex; label: string }[] = [
    { v: "male", label: "👨 Мужской" },
    { v: "female", label: "👩 Женский" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3">
      {options.map((o) => {
        const selected = value === o.v;
        return (
          <button
            key={o.v}
            type="button"
            onClick={() => onChange(o.v)}
            className="rounded-2xl border bg-tg-card px-4 py-8 text-lg font-semibold transition active:scale-[0.97]"
            style={{
              borderColor: selected ? "var(--accent)" : "transparent",
              color: selected ? "var(--accent)" : "var(--tg-text)",
              background: selected ? "var(--accent-soft)" : "var(--tg-card)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function NumberStep({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  onChange: (v: number | null) => void;
}) {
  return (
    <label className="block">
      <span className="mb-3 block text-xs uppercase tracking-wide text-tg-hint">
        {label}
      </span>
      <input
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        step={1}
        value={value ?? ""}
        autoFocus
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
        className="w-full rounded-2xl border border-[var(--glass-stroke)] bg-tg-card px-4 py-4 text-3xl font-bold text-tg-text outline-none transition focus:border-[var(--accent)]"
      />
      <span className="mt-2 block text-xs text-tg-hint">
        От {min} до {max}
      </span>
    </label>
  );
}

interface CardChoiceProps<T extends string> {
  options: { v: T; title: string; subtitle: string }[];
  value: T | null;
  onChange: (v: T) => void;
}

function CardChoiceStep<T extends string>({
  options,
  value,
  onChange,
}: CardChoiceProps<T>) {
  return (
    <div className="space-y-2">
      {options.map((o) => {
        const selected = value === o.v;
        return (
          <button
            key={o.v}
            type="button"
            onClick={() => onChange(o.v)}
            className="flex w-full items-center justify-between rounded-2xl border bg-tg-card px-4 py-4 text-left transition active:scale-[0.99]"
            style={{
              borderColor: selected ? "var(--accent)" : "transparent",
              background: selected ? "var(--accent-soft)" : "var(--tg-card)",
            }}
          >
            <div>
              <div
                className="text-[15px] font-semibold"
                style={{ color: selected ? "var(--accent)" : "var(--tg-text)" }}
              >
                {o.title}
              </div>
              {o.subtitle && (
                <div className="mt-0.5 text-xs text-tg-hint">{o.subtitle}</div>
              )}
            </div>
            {selected && (
              <span
                className="flex h-6 w-6 items-center justify-center rounded-full text-white"
                style={{ background: "var(--accent)" }}
              >
                ✓
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
