"""NutriSnap Nutrition MCP server (stdio transport).

Custom Model Context Protocol server exposing the food-resolution pipeline as
four tools. The LangGraph `nutrition_fetch_node` is the in-app MCP client (see
`app.mcp.client`); the same server also runs standalone for Claude Desktop /
MCP Inspector.

    resolve_meal_item            — composite: lookup → estimate → portion math
    lookup_food                  — local PG catalog by barcode then name/alias
    compute_meal_item_nutrition  — scale per-100g/piece macros to a portion
    estimate_food_nutrition      — gpt-4o-mini last-resort KBJU estimate

`resolve_meal_item` is what the graph actually calls — one round-trip per item
instead of three. The atomic tools stay public so external MCP clients (and
unit tests) can still inspect each step.

Run standalone:  uv run python -m app.mcp.server
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Food, FoodMetric, FoodSource
from app.db.session import async_session_factory
from app.repositories.food_repo import (
    lookup_food_by_barcode,
    search_foods_by_name,
)
from app.services.nutrition_calc import (
    compute_meal_item_nutrition as calc_item_nutrition,
)
from app.services.openai_client import NutritionEstimate, estimate_nutrition

logger = logging.getLogger(__name__)

mcp = FastMCP("nutrition")


# ─── Tool I/O schemas (JSON contract with the MCP client) ────────────────────


class FoodLookupResult(BaseModel):
    """Resolved per-unit nutrition for a food (per 100g/100ml or per 1 piece).

    `lookup_food` and `estimate_food_nutrition` share this shape so the client
    treats a catalog hit and an LLM estimate identically. `food_id` is the PG
    catalog UUID as a string, or null for ephemeral (estimated) foods.
    """

    found: bool = Field(description="True when a food was resolved")
    food_id: str | None = Field(
        default=None, description="Catalog UUID, null if ephemeral"
    )
    name: str = ""
    metric: FoodMetric = FoodMetric.GRAMS
    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    piece_weight_g: float | None = None
    source: FoodSource = FoodSource.LLM_ESTIMATE
    reason: str | None = Field(
        default=None,
        description="Why no food was returned, when `found=False` (for logging)",
    )


class NutritionResult(BaseModel):
    """Absolute nutrition for a portion. `ok=False` when the unit is incompatible."""

    ok: bool
    weight_g: float = 0.0
    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    error: str | None = None


class MealItemResolution(BaseModel):
    """End-to-end resolution for a parsed meal item: identity + portion KBJU.

    Shape the LangGraph node consumes directly — no further math needed. When
    `found=False` the caller drops the item and `reason` carries the cause for
    logs / LangSmith.
    """

    found: bool
    food_id: str | None = None
    food_name: str = ""
    weight_g: float = 0.0
    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    source: FoodSource = FoodSource.LLM_ESTIMATE
    reason: str | None = None


# ─── Core logic (plain async fns — unit-testable without the MCP layer) ──────


async def resolve_food(
    session: AsyncSession,
    name: str,
    barcode: str | None,
    *,
    brand: str | None = None,
    strict: bool = False,
) -> Food | None:
    """Try sources in priority order. See `docs/NUTRITION_LOOKUP.md`.

    The LLM estimate is intentionally NOT here — it lives in
    `estimate_food_nutrition` so the client can decide when to fall back
    without persisting hallucinations.

    `strict` (set by the reflect-retry loop) is a no-op for now — only kept
    on the signature for the future when fuzzy external search returns.
    """
    del brand, strict  # accepted for forward-compat; not used by current chain

    # 1) Local cache by barcode
    if barcode:
        hit = await lookup_food_by_barcode(session, barcode)
        if hit is not None:
            return hit

    # 2) Local cache by name / aliases / brand
    local_hits = await search_foods_by_name(session, name, limit=1)
    if local_hits:
        return local_hits[0]

    return None


def _food_to_result(food: Food) -> FoodLookupResult:
    return FoodLookupResult(
        found=True,
        food_id=str(food.id) if food.id is not None else None,
        name=food.name,
        metric=FoodMetric(food.metric),
        kcal=food.kcal,
        protein_g=food.protein_g,
        fat_g=food.fat_g,
        carbs_g=food.carbs_g,
        piece_weight_g=food.piece_weight_g,
        source=FoodSource(food.source),
    )


def is_nutrition_plausible(est: NutritionEstimate) -> bool:
    """Reject obviously-broken LLM estimates (Atwater check + zero guard).

    Real foods satisfy roughly: kcal ≈ 4·P + 9·F + 4·C  (per 100g/ml/piece).
    A 50%+ deviation means either kcal or macros are wrong, almost always
    because the model guessed without knowing the product. Reject — caller
    drops the item rather than show fake numbers.
    """
    if est.kcal <= 0:
        return False
    derived = 4 * est.protein_g + 9 * est.fat_g + 4 * est.carbs_g
    if derived <= 0:
        return False
    ratio = derived / est.kcal
    return 0.5 <= ratio <= 1.5


def compute_portion_nutrition(
    *,
    metric: FoodMetric,
    kcal: float,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    piece_weight_g: float | None,
    amount: float,
    unit: FoodMetric,
) -> NutritionResult:
    """Scale per-unit macros to a portion via the shared nutrition calculator.

    Builds a transient (un-persisted) Food so the existing
    `compute_meal_item_nutrition` does the cross-unit conversion logic. Returns
    `ok=False` with the message instead of raising, so a single bad unit never
    crashes a whole meal lookup.
    """
    transient = Food(
        name="<portion>",
        metric=metric,
        kcal=kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        piece_weight_g=piece_weight_g,
    )
    try:
        payload = calc_item_nutrition(transient, amount, unit)
    except ValueError as exc:
        return NutritionResult(ok=False, error=str(exc))
    return NutritionResult(
        ok=True,
        weight_g=payload.weight_g,
        kcal=payload.kcal,
        protein_g=payload.protein_g,
        fat_g=payload.fat_g,
        carbs_g=payload.carbs_g,
    )


# ─── MCP tools (thin wrappers over the logic above) ──────────────────────────


@mcp.tool()
async def resolve_meal_item(
    name: str,
    amount: float,
    unit: FoodMetric,
    brand: str | None = None,
    barcode: str | None = None,
    strict: bool = False,
) -> MealItemResolution:
    """Resolve a parsed item to absolute KBJU in one call.

    Pipeline: local PG (barcode then name/alias) → generic LLM estimate
    (brand dropped) → portion math.

    Unlike the atomic `estimate_food_nutrition`, the LLM fallback here does
    NOT refuse branded items — it strips the brand and estimates the generic
    food. The Atwater plausibility check (kcal ≈ 4P + 9F + 4C, ±50%) catches
    the cases where the model would hallucinate macros, so e.g. "Кефир 2.5%
    Natige" resolves via the generic estimate while a true unknown like
    "Maxler Ultra Whey" still gets rejected if the macros come back broken.
    """
    async with async_session_factory() as session:
        food = await resolve_food(session, name, barcode, brand=brand, strict=strict)

    metric = FoodMetric.GRAMS
    piece_weight_g: float | None = None
    food_id: str | None = None
    food_name = name
    source = FoodSource.LLM_ESTIMATE
    kcal = protein_g = fat_g = carbs_g = 0.0

    if food is not None:
        food_id = str(food.id) if food.id is not None else None
        food_name = food.name
        metric = FoodMetric(food.metric)
        kcal = food.kcal
        protein_g = food.protein_g
        fat_g = food.fat_g
        carbs_g = food.carbs_g
        piece_weight_g = food.piece_weight_g
        source = FoodSource(food.source)
    else:
        estimate = await estimate_nutrition(name)
        if not is_nutrition_plausible(estimate):
            return MealItemResolution(
                found=False,
                reason=(
                    f"implausible estimate (kcal={estimate.kcal} "
                    f"P={estimate.protein_g} F={estimate.fat_g} C={estimate.carbs_g})"
                ),
            )
        food_name = estimate.name
        metric = FoodMetric(estimate.metric)
        kcal = estimate.kcal
        protein_g = estimate.protein_g
        fat_g = estimate.fat_g
        carbs_g = estimate.carbs_g
        piece_weight_g = estimate.piece_weight_g

    portion = compute_portion_nutrition(
        metric=metric,
        kcal=kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        piece_weight_g=piece_weight_g,
        amount=amount,
        unit=unit,
    )
    if not portion.ok:
        return MealItemResolution(found=False, reason=portion.error)

    return MealItemResolution(
        found=True,
        food_id=food_id,
        food_name=food_name,
        weight_g=portion.weight_g,
        kcal=portion.kcal,
        protein_g=portion.protein_g,
        fat_g=portion.fat_g,
        carbs_g=portion.carbs_g,
        source=source,
    )


@mcp.tool()
async def lookup_food(
    name: str,
    barcode: str | None = None,
    brand: str | None = None,
    strict: bool = False,
) -> FoodLookupResult:
    """Resolve a food's per-unit nutrition from the local catalog.

    Order: local PG cache by barcode → local PG cache by name / alias / brand.
    Returns `found=False` when nothing matches — call `estimate_food_nutrition`
    as the last resort.

    `strict=True` is a no-op for now; it stayed on the signature for the
    reflect-retry loop, which used to disable fuzzy external search.
    """
    async with async_session_factory() as session:
        food = await resolve_food(session, name, barcode, brand=brand, strict=strict)
    if food is None:
        return FoodLookupResult(found=False, reason="no source matched")
    return _food_to_result(food)


@mcp.tool()
async def compute_meal_item_nutrition(
    metric: FoodMetric,
    kcal: float,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    amount: float,
    unit: FoodMetric,
    piece_weight_g: float | None = None,
) -> NutritionResult:
    """Scale per-100g/100ml (or per-piece) macros to a user-stated portion.

    `metric` is the food's natural metric; `unit`/`amount` is what the user ate
    (e.g. 200 g of a per-100g food → 2× the macros). Handles g↔piece conversion
    when `piece_weight_g` is known.
    """
    return compute_portion_nutrition(
        metric=metric,
        kcal=kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        piece_weight_g=piece_weight_g,
        amount=amount,
        unit=unit,
    )


@mcp.tool()
async def estimate_food_nutrition(
    name: str, brand: str | None = None
) -> FoodLookupResult:
    """Last-resort KBJU estimate from gpt-4o-mini for GENERIC foods only.

    Refuses BRANDED items (`brand` set): the model doesn't know specific
    products (e.g. "Maxler Ultra Whey") and confidently returns garbage like
    12 kcal for 30g whey — better to skip the item than show absurd KBJU.

    Also runs an Atwater plausibility check (kcal ≈ 4P + 9F + 4C) and rejects
    estimates that deviate >50%. The result is ephemeral (`food_id=null`,
    `source=llm_estimate`) and is NOT persisted, so guesses never win future
    lookups.
    """
    if brand:
        return FoodLookupResult(found=False, reason=f"branded item ({brand})")

    estimate = await estimate_nutrition(name)
    if not is_nutrition_plausible(estimate):
        return FoodLookupResult(
            found=False,
            reason=(
                f"implausible macros (kcal={estimate.kcal} "
                f"P={estimate.protein_g} F={estimate.fat_g} C={estimate.carbs_g})"
            ),
        )
    return FoodLookupResult(
        found=True,
        food_id=None,
        name=estimate.name,
        metric=FoodMetric(estimate.metric),
        kcal=estimate.kcal,
        protein_g=estimate.protein_g,
        fat_g=estimate.fat_g,
        carbs_g=estimate.carbs_g,
        piece_weight_g=estimate.piece_weight_g,
        source=FoodSource.LLM_ESTIMATE,
    )


def main() -> None:
    """Entrypoint for `python -m app.mcp.server` — serves over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
