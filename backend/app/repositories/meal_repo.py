"""Meal + MealItem persistence."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    FoodMetric,
    InputSource,
    Meal,
    MealItem,
    MealType,
    User,
)


@dataclass(slots=True)
class MealItemPayload:
    """A single item to log inside a meal (already nutrition-computed)."""

    food_name: str
    amount: float
    unit: FoodMetric
    weight_g: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    food_id: UUID | None = None


@dataclass(slots=True)
class DailySummary:
    user_id: UUID
    summary_date: date
    total_kcal: float
    total_protein_g: float
    total_fat_g: float
    total_carbs_g: float
    meals_count: int
    target_kcal: int | None
    target_protein_g: int | None
    target_fat_g: int | None
    target_carbs_g: int | None


async def log_meal_with_items(
    session: AsyncSession,
    *,
    user: User,
    meal_type: MealType,
    items: list[MealItemPayload],
    eaten_at: datetime | None = None,
    source: InputSource = InputSource.TEXT,
    raw_input: str | None = None,
    tg_message_id: int | None = None,
) -> Meal:
    """Persist a meal with its items. Idempotent by (user_id, tg_message_id).

    If `tg_message_id` is set and a meal already exists for it, returns the
    existing meal without inserting duplicates.
    """
    if eaten_at is None:
        eaten_at = datetime.now(timezone.utc)

    # Idempotency: try to find existing meal for this Telegram update first.
    if tg_message_id is not None:
        existing = await session.scalar(
            select(Meal).where(
                Meal.user_id == user.id, Meal.tg_message_id == tg_message_id
            )
        )
        if existing is not None:
            return existing

    meal = Meal(
        user_id=user.id,
        meal_type=meal_type,
        eaten_at=eaten_at,
        source=source,
        raw_input=raw_input,
        tg_message_id=tg_message_id,
    )
    meal.items = [
        MealItem(
            food_name=it.food_name,
            amount=it.amount,
            unit=it.unit,
            weight_g=it.weight_g,
            kcal=it.kcal,
            protein_g=it.protein_g,
            fat_g=it.fat_g,
            carbs_g=it.carbs_g,
            food_id=it.food_id,
        )
        for it in items
    ]
    session.add(meal)
    await session.commit()
    await session.refresh(meal, attribute_names=["items"])
    return meal


async def get_meal_with_items(session: AsyncSession, meal_id: UUID) -> Meal | None:
    return await session.scalar(
        select(Meal).where(Meal.id == meal_id).options(selectinload(Meal.items))
    )


async def fetch_daily_summary(
    session: AsyncSession,
    user: User,
    summary_date: date,
) -> DailySummary:
    """Aggregate KBJU over all meals for the given date (no stored totals)."""
    day_start = datetime.combine(summary_date, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    stmt = (
        select(
            func.coalesce(func.sum(MealItem.kcal), 0).label("kcal"),
            func.coalesce(func.sum(MealItem.protein_g), 0).label("protein_g"),
            func.coalesce(func.sum(MealItem.fat_g), 0).label("fat_g"),
            func.coalesce(func.sum(MealItem.carbs_g), 0).label("carbs_g"),
            func.count(func.distinct(Meal.id)).label("meals_count"),
        )
        .select_from(Meal)
        .join(MealItem, MealItem.meal_id == Meal.id)
        .where(
            Meal.user_id == user.id,
            Meal.eaten_at >= day_start,
            Meal.eaten_at < day_end,
        )
    )
    row = (await session.execute(stmt)).one()
    return DailySummary(
        user_id=user.id,
        summary_date=summary_date,
        total_kcal=float(row.kcal),
        total_protein_g=float(row.protein_g),
        total_fat_g=float(row.fat_g),
        total_carbs_g=float(row.carbs_g),
        meals_count=int(row.meals_count),
        target_kcal=user.tdee_kcal,
        target_protein_g=user.target_protein_g,
        target_fat_g=user.target_fat_g,
        target_carbs_g=user.target_carbs_g,
    )


async def fetch_meals_for_day(
    session: AsyncSession, user: User, day: date
) -> list[Meal]:
    """All meals (with items) for a UTC calendar day, ordered by time."""
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(Meal)
        .where(
            Meal.user_id == user.id,
            Meal.eaten_at >= day_start,
            Meal.eaten_at < day_end,
        )
        .order_by(Meal.eaten_at)
        .options(selectinload(Meal.items))
    )
    return list((await session.scalars(stmt)).all())


async def fetch_month_day_totals(
    session: AsyncSession, user: User, year: int, month: int
) -> dict[date, float]:
    """Sum of kcal per UTC calendar day for a month — one grouped query.

    Used by the Mini App calendar to colour days without 30+ requests.
    """
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    day = func.date(func.timezone("UTC", Meal.eaten_at)).label("day")
    stmt = (
        select(day, func.coalesce(func.sum(MealItem.kcal), 0).label("kcal"))
        .select_from(Meal)
        .join(MealItem, MealItem.meal_id == Meal.id)
        .where(
            Meal.user_id == user.id,
            Meal.eaten_at >= month_start,
            Meal.eaten_at < month_end,
        )
        .group_by(day)
    )
    rows = (await session.execute(stmt)).all()
    return {r.day: float(r.kcal) for r in rows}


async def fetch_recent_meals(
    session: AsyncSession, user: User, limit: int = 10
) -> list[Meal]:
    stmt = (
        select(Meal)
        .where(Meal.user_id == user.id)
        .order_by(Meal.eaten_at.desc())
        .limit(limit)
        .options(selectinload(Meal.items))
    )
    return list((await session.scalars(stmt)).all())


async def delete_meal(session: AsyncSession, meal_id: UUID) -> bool:
    meal = await session.get(Meal, meal_id)
    if meal is None:
        return False
    await session.delete(meal)
    await session.commit()
    return True
