"""Pydantic DTOs for the Mini App API (response/request contracts)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    targets: MacroTargets


class ProfileUpdate(BaseModel):
    """Body for PUT /api/me — recomputes daily targets on save."""
    sex: Sex
    weight_kg: float = Field(gt=20, lt=400)
    height_cm: float = Field(gt=80, lt=260)
    age: int = Field(gt=5, lt=130)
    activity: ActivityLevel
    goal: Goal


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
