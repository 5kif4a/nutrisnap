// Mirrors backend app/api/schemas.py

export type Sex = "male" | "female";
export type ActivityLevel =
  | "sedentary"
  | "light"
  | "moderate"
  | "active"
  | "very_active";
export type Goal = "lose" | "maintain" | "gain";
export type MealType = "breakfast" | "lunch" | "dinner" | "snack";
export type FoodMetric = "g" | "ml" | "piece" | "serving";

export interface MacroTargets {
  kcal: number | null;
  protein_g: number | null;
  fat_g: number | null;
  carbs_g: number | null;
}

export interface UserProfile {
  telegram_id: number;
  first_name: string | null;
  username: string | null;
  is_onboarded: boolean;
  sex: Sex | null;
  weight_kg: number | null;
  height_cm: number | null;
  age: number | null;
  activity: ActivityLevel | null;
  goal: Goal | null;
  targets: MacroTargets;
}

export interface ProfileUpdate {
  sex: Sex;
  weight_kg: number;
  height_cm: number;
  age: number;
  activity: ActivityLevel;
  goal: Goal;
}

export interface MealItemOut {
  id: string;
  food_name: string;
  amount: number;
  unit: FoodMetric;
  weight_g: number;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface MealOut {
  id: string;
  meal_type: MealType;
  eaten_at: string;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  items: MealItemOut[];
}

export interface DayTotals {
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface DayResponse {
  date: string;
  totals: DayTotals;
  targets: MacroTargets;
  meals: MealOut[];
}
