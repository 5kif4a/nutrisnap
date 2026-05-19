import {
  Button,
  Input,
  List,
  SegmentedControl,
  Section,
  Select,
} from "@telegram-apps/telegram-ui";
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
  { v: "maintain", label: "⚖️ Вес" },
  { v: "gain", label: "📈 Набрать" },
];

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
    <div className="mx-auto max-w-md pb-24">
      <List>
        <Section
          header={`Привет, ${greetingName()} 👋`}
          footer="Параметры для расчёта суточной нормы КБЖУ (Mifflin-St Jeor)."
        >
          {profile?.targets.kcal && (
            <div className="grid grid-cols-4 gap-2 px-4 py-3 text-center">
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
        </Section>

        <Section header="Параметры">
          <div className="px-4 pt-3">
            <SegmentedControl>
              {(["male", "female"] as Sex[]).map((s) => (
                <SegmentedControl.Item
                  key={s}
                  selected={form.sex === s}
                  onClick={() => setForm((f) => ({ ...f, sex: s }))}
                >
                  {s === "male" ? "👨 Мужской" : "👩 Женский"}
                </SegmentedControl.Item>
              ))}
            </SegmentedControl>
          </div>

          <Input
            type="number"
            header="Вес, кг"
            value={form.weight_kg}
            onChange={num("weight_kg")}
          />
          <Input
            type="number"
            header="Рост, см"
            value={form.height_cm}
            onChange={num("height_cm")}
          />
          <Input
            type="number"
            header="Возраст"
            value={form.age}
            onChange={num("age")}
          />

          <Select
            header="Активность"
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
          </Select>

          <div className="px-4 py-3">
            <SegmentedControl>
              {GOAL_OPTS.map((o) => (
                <SegmentedControl.Item
                  key={o.v}
                  selected={form.goal === o.v}
                  onClick={() => setForm((f) => ({ ...f, goal: o.v }))}
                >
                  {o.label}
                </SegmentedControl.Item>
              ))}
            </SegmentedControl>
          </div>
        </Section>

        {error && (
          <div className="mx-4 rounded-xl bg-red-100 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="px-4 py-2">
          <Button
            size="l"
            stretched
            mode="filled"
            loading={status === "saving"}
            onClick={save}
          >
            {status === "saved"
              ? "✓ Сохранено"
              : "Сохранить и пересчитать норму"}
          </Button>
        </div>
      </List>
    </div>
  );
}
