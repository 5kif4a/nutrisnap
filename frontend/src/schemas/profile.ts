/**
 * Zod schema for the Profile form — mirrors backend `ProfileUpdate`
 * (app/api/schemas.py) so client-side errors match what the API would reject.
 *
 * Cross-field rules:
 *  - `target_weight_kg` is required when goal ∈ {lose, gain}, ignored on maintain.
 *  - For goal=lose, target must be strictly less than current weight.
 *  - For goal=gain, target must be strictly greater than current weight.
 *  - When `manual_targets=true`, all four target_* macros are required.
 */

import { z } from "zod";

export const profileFormSchema = z
  .object({
    sex: z.enum(["male", "female"]),
    weight_kg: z
      .number({ message: "Введи вес" })
      .gt(20, "Слишком мало")
      .lt(400, "Слишком много"),
    height_cm: z
      .number({ message: "Введи рост" })
      .gt(80, "Слишком мало")
      .lt(260, "Слишком много"),
    age: z
      .number({ message: "Введи возраст" })
      .int("Без дробной части")
      .gt(5, "Слишком мало")
      .lt(130, "Слишком много"),
    activity: z.enum([
      "sedentary",
      "light",
      "moderate",
      "active",
      "very_active",
    ]),
    goal: z.enum(["lose", "maintain", "gain"]),
    target_weight_kg: z
      .number()
      .gt(20, "Слишком мало")
      .lt(400, "Слишком много")
      .nullable()
      .optional(),

    manual_targets: z.boolean(),
    target_kcal: z
      .number()
      .int("Целое число")
      .gte(500, "Минимум 500")
      .lte(10000, "Максимум 10000")
      .nullable()
      .optional(),
    target_protein_g: z
      .number()
      .int("Целое число")
      .gte(0, "Не отрицательное")
      .lte(1000, "Максимум 1000")
      .nullable()
      .optional(),
    target_fat_g: z
      .number()
      .int("Целое число")
      .gte(0, "Не отрицательное")
      .lte(1000, "Максимум 1000")
      .nullable()
      .optional(),
    target_carbs_g: z
      .number()
      .int("Целое число")
      .gte(0, "Не отрицательное")
      .lte(2000, "Максимум 2000")
      .nullable()
      .optional(),
  })
  .superRefine((v, ctx) => {
    // goal / target_weight_kg coupling
    if (v.goal !== "maintain") {
      if (v.target_weight_kg == null) {
        ctx.addIssue({
          code: "custom",
          message: "Укажи целевой вес",
          path: ["target_weight_kg"],
        });
      } else if (v.goal === "lose" && v.target_weight_kg >= v.weight_kg) {
        ctx.addIssue({
          code: "custom",
          message: "Должен быть меньше текущего",
          path: ["target_weight_kg"],
        });
      } else if (v.goal === "gain" && v.target_weight_kg <= v.weight_kg) {
        ctx.addIssue({
          code: "custom",
          message: "Должен быть больше текущего",
          path: ["target_weight_kg"],
        });
      }
    }

    // manual_targets requires all four macro fields
    if (v.manual_targets) {
      const fields = [
        "target_kcal",
        "target_protein_g",
        "target_fat_g",
        "target_carbs_g",
      ] as const;
      for (const f of fields) {
        if (v[f] == null) {
          ctx.addIssue({
            code: "custom",
            message: "Обязательно",
            path: [f],
          });
        }
      }
    }
  });

export type ProfileFormValues = z.infer<typeof profileFormSchema>;
