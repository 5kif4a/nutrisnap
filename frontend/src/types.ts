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
  target_weight_kg: number | null;
  targets: MacroTargets;
}

export interface ProfileUpdate {
  sex: Sex;
  weight_kg: number;
  height_cm: number;
  age: number;
  activity: ActivityLevel;
  goal: Goal;
  // Only meaningful for LOSE / GAIN; backend stores NULL when goal=MAINTAIN.
  target_weight_kg?: number | null;
  // When `manual_targets` is true the four target_* fields override the
  // Mifflin-St Jeor auto-calc on the backend.
  manual_targets?: boolean;
  target_kcal?: number | null;
  target_protein_g?: number | null;
  target_fat_g?: number | null;
  target_carbs_g?: number | null;
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

export type DayStatus = "green" | "yellow" | "red" | "empty";

export interface MonthDay {
  date: string;
  kcal: number;
  status: DayStatus;
}

export interface MonthResponse {
  month: string; // YYYY-MM
  target_kcal: number | null;
  days: MonthDay[];
}

export interface QuickAddFoodOut {
  food_name: string;
  food_id: string | null;
  amount: number;
  unit: FoodMetric;
  weight_g: number;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  frequency: number;
}

export interface QuickAddRequest {
  food_name: string;
  amount: number;
  unit: FoodMetric;
  weight_g: number;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  meal_type: MealType;
  food_id?: string | null;
  eaten_at?: string | null;
}

export interface BulkAddItem {
  food_name: string;
  amount: number;
  unit: FoodMetric;
  weight_g: number;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  food_id?: string | null;
}

export interface BulkAddRequest {
  meal_type: MealType;
  items: BulkAddItem[];
  eaten_at?: string | null;
}

export interface CreateCustomFoodRequest {
  name: string;
  brand?: string | null;
  metric: FoodMetric;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  piece_weight_g?: number | null;
}

export interface ResolvedItem {
  food_name: string;
  amount: number;
  unit: FoodMetric;
  weight_g: number;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  food_id?: string | null;
}

export interface MealEntryResolveResponse {
  items: ResolvedItem[];
  response_text?: string | null;
  reason?: string | null;
}
