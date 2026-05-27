"""Daily nutrition targets — TDEE + macros."""

from dataclasses import dataclass

from app.db.models import ActivityLevel, Goal, Sex

ACTIVITY_MULTIPLIERS: dict[ActivityLevel, float] = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHT: 1.375,
    ActivityLevel.MODERATE: 1.55,
    ActivityLevel.ACTIVE: 1.725,
    ActivityLevel.VERY_ACTIVE: 1.9,
}

GOAL_KCAL_DELTA: dict[Goal, int] = {
    Goal.LOSE: -500,
    Goal.MAINTAIN: 0,
    Goal.GAIN: 300,
}


@dataclass(slots=True)
class DailyTargets:
    tdee_kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int


def compute_bmr_mifflin(
    sex: Sex, weight_kg: float, height_cm: float, age: int
) -> float:
    """Mifflin-St Jeor basal metabolic rate (kcal/day)."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + (5 if sex is Sex.MALE else -161)


def compute_daily_targets(
    sex: Sex,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity: ActivityLevel,
    goal: Goal,
) -> DailyTargets:
    bmr = compute_bmr_mifflin(sex, weight_kg, height_cm, age)
    tdee = bmr * ACTIVITY_MULTIPLIERS[activity] + GOAL_KCAL_DELTA[goal]
    tdee = max(int(round(tdee)), 1200)  # safety floor

    # Macros split: 30% protein / 25% fat / 45% carbs (common starting point)
    protein_g = int(round(tdee * 0.30 / 4))
    fat_g = int(round(tdee * 0.25 / 9))
    carbs_g = int(round(tdee * 0.45 / 4))

    return DailyTargets(
        tdee_kcal=tdee,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
    )
