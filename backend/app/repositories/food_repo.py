"""Food catalog persistence + cache + quick-add queries."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import case, desc, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Food,
    FoodMetric,
    FoodSource,
    Meal,
    MealItem,
    MealType,
    User,
)
from app.rag.qdrant import schedule_food_indexing


@dataclass(slots=True)
class ExternalFoodPayload:
    """Normalized food info from any external source (OFF, FatSecret, Vision)."""

    name: str
    metric: FoodMetric
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    source: FoodSource
    brand: str | None = None
    barcode: str | None = None
    cuisine: str | None = None
    piece_weight_g: float | None = None
    aliases: list[str] | None = None
    external_id: str | None = None
    servings: list[dict] | None = None


@dataclass(slots=True)
class QuickAddItem:
    """Snapshot of a previously-eaten item for one-tap re-logging."""

    food_name: str
    food_id: UUID | None
    amount: float
    unit: FoodMetric
    weight_g: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    frequency: int  # how many times user ate this in the window


async def search_foods_by_name(
    session: AsyncSession, query: str, limit: int = 10
) -> list[Food]:
    """Search local catalog by name OR aliases. Case-insensitive.

    Results are ordered by source trust — curated (hand-verified) wins over
    FatSecret / LLM-estimate which historically have produced noisy text hits.
    """
    pattern = f"%{query.strip()}%"
    source_priority = case(
        (Food.source == FoodSource.CURATED, 0),
        (Food.source == FoodSource.USER_RECIPE, 1),
        (Food.source == FoodSource.FATSECRET, 2),
        (Food.source == FoodSource.CUSTOM, 3),
        (Food.source == FoodSource.LLM_ESTIMATE, 4),
        else_=99,
    )
    stmt = (
        select(Food)
        .where(
            or_(
                Food.name.ilike(pattern),
                # ANY-aliases match: unnest aliases and check each
                text(
                    "EXISTS (SELECT 1 FROM unnest(aliases) a WHERE a ILIKE :pat)"
                ).bindparams(pat=pattern),
                Food.brand.ilike(pattern),
            )
        )
        .order_by(source_priority, Food.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def lookup_food_by_barcode(session: AsyncSession, barcode: str) -> Food | None:
    return await session.scalar(select(Food).where(Food.barcode == barcode))


async def upsert_food_from_external(
    session: AsyncSession,
    payload: ExternalFoodPayload,
    *,
    created_by_user_id: UUID | None = None,
) -> Food:
    """Insert a new Food or update if barcode already exists (atomic UPSERT)."""
    aliases = payload.aliases or []
    servings = payload.servings or []

    values = {
        "name": payload.name,
        "aliases": aliases,
        "brand": payload.brand,
        "barcode": payload.barcode,
        "cuisine": payload.cuisine,
        "metric": payload.metric,
        "kcal": payload.kcal,
        "protein_g": payload.protein_g,
        "fat_g": payload.fat_g,
        "carbs_g": payload.carbs_g,
        "piece_weight_g": payload.piece_weight_g,
        "servings": servings,
        "source": payload.source,
        "external_id": payload.external_id,
        "created_by_user_id": created_by_user_id,
    }

    if payload.barcode is not None:
        stmt = (
            pg_insert(Food)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["barcode"],
                set_={
                    k: v
                    for k, v in values.items()
                    if k not in {"barcode", "created_by_user_id"}
                },
            )
            .returning(Food)
        )
        result = await session.scalars(stmt)
        food = result.one()
    else:
        food = Food(**values)
        session.add(food)
        await session.flush()

    await session.commit()
    # Fire-and-forget: index the new/updated catalog row in Qdrant so the
    # recommender sees it without waiting for the next manual `ingest_foods`.
    schedule_food_indexing(food)
    return food


async def save_user_recipe(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    ingredients_total_kcal: float,
    ingredients_total_protein_g: float,
    ingredients_total_fat_g: float,
    ingredients_total_carbs_g: float,
    cooked_weight_g: float,
    aliases: list[str] | None = None,
) -> Food:
    """Persist a user-cooked recipe as a `Food` row with per-100g macros.

    Raw ingredient totals are normalized to the cooked dish weight. The next
    time the user eats the same dish they just say "150 г X" and the bot
    pulls the saved row from the local catalog without any LLM call.
    """
    if cooked_weight_g <= 0:
        raise ValueError("cooked_weight_g must be positive")
    factor = 100.0 / cooked_weight_g
    food = Food(
        name=name.strip(),
        aliases=aliases or [],
        metric=FoodMetric.GRAMS,
        kcal=ingredients_total_kcal * factor,
        protein_g=ingredients_total_protein_g * factor,
        fat_g=ingredients_total_fat_g * factor,
        carbs_g=ingredients_total_carbs_g * factor,
        source=FoodSource.USER_RECIPE,
        created_by_user_id=user.id,
    )
    session.add(food)
    await session.commit()
    await session.refresh(food)
    schedule_food_indexing(food)
    return food


async def list_recent_foods_per_meal_type(
    session: AsyncSession,
    user: User,
    meal_type: MealType,
    limit: int = 5,
) -> list[QuickAddItem]:
    """Latest distinct foods user ate for this meal type."""
    stmt = (
        select(
            MealItem.food_name,
            MealItem.food_id,
            MealItem.amount,
            MealItem.unit,
            MealItem.weight_g,
            MealItem.kcal,
            MealItem.protein_g,
            MealItem.fat_g,
            MealItem.carbs_g,
            func.max(Meal.eaten_at).label("last_eaten"),
        )
        .select_from(MealItem)
        .join(Meal, Meal.id == MealItem.meal_id)
        .where(Meal.user_id == user.id, Meal.meal_type == meal_type)
        .group_by(
            MealItem.food_name,
            MealItem.food_id,
            MealItem.amount,
            MealItem.unit,
            MealItem.weight_g,
            MealItem.kcal,
            MealItem.protein_g,
            MealItem.fat_g,
            MealItem.carbs_g,
        )
        .order_by(desc("last_eaten"))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        QuickAddItem(
            food_name=r.food_name,
            food_id=r.food_id,
            amount=r.amount,
            unit=FoodMetric(r.unit),
            weight_g=r.weight_g,
            kcal=r.kcal,
            protein_g=r.protein_g,
            fat_g=r.fat_g,
            carbs_g=r.carbs_g,
            frequency=1,
        )
        for r in rows
    ]


async def list_frequent_foods_per_meal_type(
    session: AsyncSession,
    user: User,
    meal_type: MealType,
    limit: int = 5,
    days_back: int = 30,
) -> list[QuickAddItem]:
    """Most-eaten foods in this meal type over the last `days_back` days."""
    window_start = func.now() - timedelta(days=days_back)
    stmt = (
        select(
            MealItem.food_name,
            func.count().label("freq"),
            func.avg(MealItem.amount).label("avg_amount"),
            # all rows of same food_name share unit in 99% cases — pick most common
            func.mode().within_group(MealItem.unit).label("unit"),
            func.avg(MealItem.weight_g).label("avg_weight_g"),
            func.avg(MealItem.kcal).label("avg_kcal"),
            func.avg(MealItem.protein_g).label("avg_protein_g"),
            func.avg(MealItem.fat_g).label("avg_fat_g"),
            func.avg(MealItem.carbs_g).label("avg_carbs_g"),
        )
        .select_from(MealItem)
        .join(Meal, Meal.id == MealItem.meal_id)
        .where(
            Meal.user_id == user.id,
            Meal.meal_type == meal_type,
            Meal.eaten_at > window_start,
        )
        .group_by(MealItem.food_name)
        .having(func.count() >= 2)
        .order_by(desc("freq"))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        QuickAddItem(
            food_name=r.food_name,
            food_id=None,
            amount=float(r.avg_amount),
            unit=FoodMetric(r.unit),
            weight_g=float(r.avg_weight_g),
            kcal=float(r.avg_kcal),
            protein_g=float(r.avg_protein_g),
            fat_g=float(r.avg_fat_g),
            carbs_g=float(r.avg_carbs_g),
            frequency=int(r.freq),
        )
        for r in rows
    ]
