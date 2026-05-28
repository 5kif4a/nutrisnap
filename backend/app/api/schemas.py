"""Pydantic DTOs for the Mini App API (response/request contracts)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ActivityLevel, FoodMetric, Goal, MealType, Sex


class MacroTargets(BaseModel):
    kcal: int | None
    protein_g: int | None
    fat_g: int | None
    carbs_g: int | None


class UserProfile(BaseModel):
    telegram_id: int
    first_name: str | None
    username: str | None
    is_onboarded: bool
    sex: Sex | None
    weight_kg: float | None
    height_cm: float | None
    age: int | None
    activity: ActivityLevel | None
    goal: Goal | None
    target_weight_kg: float | None
    targets: MacroTargets


class ProfileUpdate(BaseModel):
    """Body for PUT /api/me — recomputes daily targets on save.

    When `manual_targets=True`, the four target_* fields override the
    Mifflin-St Jeor auto-calc. Otherwise the targets are recomputed from
    sex / weight / height / age / activity / goal as before.
    """

    sex: Sex
    weight_kg: float = Field(gt=20, lt=400)
    height_cm: float = Field(gt=80, lt=260)
    age: int = Field(gt=5, lt=130)
    activity: ActivityLevel
    goal: Goal
    # Only meaningful for LOSE / GAIN goals; ignored when goal=MAINTAIN.
    target_weight_kg: float | None = Field(default=None, gt=20, lt=400)

    manual_targets: bool = False
    target_kcal: int | None = Field(default=None, ge=500, le=10000)
    target_protein_g: int | None = Field(default=None, ge=0, le=1000)
    target_fat_g: int | None = Field(default=None, ge=0, le=1000)
    target_carbs_g: int | None = Field(default=None, ge=0, le=2000)

    @model_validator(mode="after")
    def _check_goal_target_weight(self) -> "ProfileUpdate":
        """Cross-field validation for goal + target_weight_kg."""
        if self.goal is Goal.MAINTAIN:
            # MAINTAIN ignores any target weight — normalize to None so the
            # repo doesn't have to second-guess the caller.
            self.target_weight_kg = None
            return self

        if self.target_weight_kg is None:
            raise ValueError(
                "target_weight_kg is required when goal is 'lose' or 'gain'",
            )
        if self.goal is Goal.LOSE and self.target_weight_kg >= self.weight_kg:
            raise ValueError(
                "target_weight_kg must be less than weight_kg for goal=lose",
            )
        if self.goal is Goal.GAIN and self.target_weight_kg <= self.weight_kg:
            raise ValueError(
                "target_weight_kg must be greater than weight_kg for goal=gain",
            )
        return self

    @model_validator(mode="after")
    def _check_manual_targets(self) -> "ProfileUpdate":
        """When manual_targets=True, all four target_* fields must be set."""
        if not self.manual_targets:
            return self
        missing = [
            name
            for name, value in (
                ("target_kcal", self.target_kcal),
                ("target_protein_g", self.target_protein_g),
                ("target_fat_g", self.target_fat_g),
                ("target_carbs_g", self.target_carbs_g),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                f"manual_targets=true requires: {', '.join(missing)}",
            )
        return self


class MealItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    food_name: str
    amount: float
    unit: FoodMetric
    weight_g: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


class MealOut(BaseModel):
    id: UUID
    meal_type: MealType
    eaten_at: datetime
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    items: list[MealItemOut]


class DayTotals(BaseModel):
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


class DayResponse(BaseModel):
    date: str  # YYYY-MM-DD
    totals: DayTotals
    targets: MacroTargets
    meals: list[MealOut]


class DayStatus(StrEnum):
    GREEN = "green"  # в норме (kcal близко к цели)
    YELLOW = "yellow"  # немного (заметно ниже цели)
    RED = "red"  # мало (сильно ниже цели)
    EMPTY = "empty"  # нет записей / нет нормы


class MonthDay(BaseModel):
    date: str  # YYYY-MM-DD
    kcal: float
    status: DayStatus


class MonthResponse(BaseModel):
    month: str  # YYYY-MM
    target_kcal: int | None
    days: list[MonthDay]


class QuickAddFoodOut(BaseModel):
    """One entry in the 'recent' / 'frequent' lists — pre-computed nutrition
    for the portion size the user typically eats."""

    food_name: str
    food_id: UUID | None
    amount: float
    unit: FoodMetric
    weight_g: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    frequency: int = Field(
        description="How many times the user ate this in the lookback window"
    )


class RecommendationItemOut(BaseModel):
    food_id: str
    name: str
    brand: str | None = None
    suggested_grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    rationale_short: str


class RecommendationResponse(BaseModel):
    summary: str
    items: list[RecommendationItemOut]


class RecommendRequest(BaseModel):
    """Optional body for POST /api/recommendations — pass a free-form prompt
    to bias the recommender towards a specific craving / constraint."""

    query: str | None = Field(
        default=None,
        description="Free-text query (e.g. 'high-protein snack'). When omitted, "
        "the recommender derives intent from the user's macro deficit.",
    )


class QuickAddRequest(BaseModel):
    """Body for POST /api/meals/quick-add — log one item as a standalone meal.

    For multi-item quick-add the client should call this once per item OR
    use the future /api/meals/bulk endpoint. Keeping it single for now to
    match the 'tap to log' UX of stock diary apps.
    """

    food_name: str
    amount: float = Field(gt=0)
    unit: FoodMetric
    weight_g: float = Field(ge=0)
    kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    meal_type: MealType
    food_id: UUID | None = None
    eaten_at: datetime | None = Field(
        default=None,
        description="Defaults to now. Pass to backfill historical entries.",
    )
