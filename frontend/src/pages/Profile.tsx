import { useEffect, useState } from "react";
import { api } from "../lib/api";
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
  { v: "maintain", label: "⚖️ Держать вес" },
  { v: "gain", label: "📈 Набрать" },
];

const FIELD =
  "w-full rounded-xl border border-tg-border bg-tg-bg px-3 py-2.5 text-tg-text outline-none";

export function Profile() {
  const [form, setForm] = useState<ProfileUpdate>({
    sex: "male",
    weight_kg: 70,
    height_cm: 175,
    age: 30,
    activity: "moderate",
    goal: "maintain",
  });
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);

  const apply = (p: UserProfile) => {
    setProfile(p);
    setForm({
      sex: p.sex ?? "male",
      weight_kg: p.weight_kg ?? 70,
      height_cm: p.height_cm ?? 175,
      age: p.age ?? 30,
      activity: p.activity ?? "moderate",
      goal: p.goal ?? "maintain",
    });
  };

  useEffect(() => {
    api
      .getMe()
      .then(apply)
      .catch((e) => setError((e as Error).message));
  }, []);

  const save = async () => {
    setStatus("saving");
    setError(null);
    try {
      apply(await api.updateMe(form));
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 2000);
    } catch (e) {
      setError((e as Error).message);
      setStatus("error");
    }
  };

  const num =
    (k: "weight_kg" | "height_cm" | "age") =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [k]: Number(e.target.value) }));

  return (
    <div className="mx-auto max-w-md px-4 pb-24 pt-4">
      <h1 className="mb-1 text-xl font-bold text-tg-text">
        Привет, {greetingName()} 👋
      </h1>
      <p className="mb-5 text-sm text-tg-hint">
        Параметры для расчёта суточной нормы КБЖУ.
      </p>

      {profile?.targets.kcal && (
        <div className="mb-5 grid grid-cols-4 gap-2 rounded-2xl bg-tg-card p-4 text-center shadow-sm">
          {[
            ["🔥", profile.targets.kcal, "ккал"],
            ["🥩", profile.targets.protein_g, "Б"],
            ["🥑", profile.targets.fat_g, "Ж"],
            ["🍞", profile.targets.carbs_g, "У"],
          ].map(([icon, val, lbl]) => (
            <div key={lbl as string}>
              <div className="text-lg">{icon as string}</div>
              <div className="font-bold text-tg-text">{val as number}</div>
              <div className="text-xs text-tg-hint">{lbl as string}</div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-4 rounded-2xl bg-tg-card p-4 shadow-sm">
        <div>
          <label className="mb-1 block text-sm text-tg-hint">Пол</label>
          <div className="flex gap-2">
            {(["male", "female"] as Sex[]).map((s) => (
              <button
                key={s}
                onClick={() => setForm((f) => ({ ...f, sex: s }))}
                className={`flex-1 rounded-xl py-2.5 text-sm font-medium ${
                  form.sex === s
                    ? "bg-tg-button text-tg-button-text"
                    : "border border-tg-border text-tg-text"
                }`}
              >
                {s === "male" ? "👨 Мужской" : "👩 Женский"}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="mb-1 block text-sm text-tg-hint">Вес, кг</label>
            <input
              type="number"
              className={FIELD}
              value={form.weight_kg}
              onChange={num("weight_kg")}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-tg-hint">Рост, см</label>
            <input
              type="number"
              className={FIELD}
              value={form.height_cm}
              onChange={num("height_cm")}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-tg-hint">Возраст</label>
            <input
              type="number"
              className={FIELD}
              value={form.age}
              onChange={num("age")}
            />
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm text-tg-hint">Активность</label>
          <select
            className={FIELD}
            value={form.activity}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                activity: e.target.value as ActivityLevel,
              }))
            }
          >
            {ACTIVITY_OPTS.map((o) => (
              <option key={o.v} value={o.v}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm text-tg-hint">Цель</label>
          <div className="flex gap-2">
            {GOAL_OPTS.map((o) => (
              <button
                key={o.v}
                onClick={() => setForm((f) => ({ ...f, goal: o.v }))}
                className={`flex-1 rounded-xl py-2.5 text-xs font-medium ${
                  form.goal === o.v
                    ? "bg-tg-button text-tg-button-text"
                    : "border border-tg-border text-tg-text"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-red-100 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <button
        onClick={save}
        disabled={status === "saving"}
        className="mt-5 w-full rounded-2xl bg-tg-button py-3 font-semibold text-tg-button-text shadow-lg disabled:opacity-50"
      >
        {status === "saving"
          ? "Сохраняю…"
          : status === "saved"
            ? "✓ Сохранено"
            : "Сохранить и пересчитать норму"}
      </button>
    </div>
  );
}
