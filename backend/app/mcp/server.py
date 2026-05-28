"""NutriSnap Nutrition MCP server (stdio transport).

Custom Model Context Protocol server exposing the food-resolution pipeline as
three meaningful tools. The LangGraph `nutrition_fetch_node` is the in-app MCP
client (see `app.mcp.client`); the same server also runs standalone for Claude
Desktop / MCP Inspector.

    lookup_food                  — local cache → OFF → FatSecret chain (+ upsert)
    compute_meal_item_nutrition  — scale per-100g/piece macros to a portion
    estimate_food_nutrition      — gpt-4o-mini last-resort KBJU estimate

Run standalone:  uv run python -m app.mcp.server
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Food, FoodMetric, FoodSource
from app.db.session import async_session_factory
from app.repositories.food_repo import (
    lookup_food_by_barcode,
    search_foods_by_name,
    upsert_food_from_external,
)
from app.services import fatsecret as fs
from app.services import openfoodfacts as off
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


# ─── Core logic (plain async fns — unit-testable without the MCP layer) ──────


async def resolve_food(
    session: AsyncSession,
    name: str,
    barcode: str | None,
    *,
    brand: str | None = None,
    strict: bool = False,
) -> Food | None:
    """Try sources in priority order; cache external hits into local PG.

    Mirrors steps 1–5 of `docs/NUTRITION_LOOKUP.md`. The LLM estimate (step 6)
    is intentionally NOT here — it lives in `estimate_food_nutrition` so the
    client can decide when to fall back without persisting hallucinations.

    `brand` hard-filters Open Food Facts text results (case-insensitive
    substring on the OFF `brands` field). In `strict` mode (used by the
    reflect-retry loop) we skip fuzzy text search in OFF and FatSecret — those
    are the steps that produce the worst hallucinations ("Nuts 66" → some
    random nut-butter row). Barcode lookups always stay (ground truth).
    """
    # 1) Local cache by barcode
    if barcode:
        hit = await lookup_food_by_barcode(session, barcode)
        if hit is not None:
            return hit

    # 2) Local cache by name / aliases / brand
    local_hits = await search_foods_by_name(session, name, limit=1)
    if local_hits:
        return local_hits[0]

    # 3) Open Food Facts by barcode
    if barcode:
        off_hit = await off.lookup_food_by_barcode(barcode)
        if off_hit is not None:
            return await upsert_food_from_external(session, off_hit)

    if not strict:
        # 4) Open Food Facts text search — pass brand so OFF hard-filters on it
        off_results = await off.search_foods_by_text(name, brand=brand, limit=1)
        if off_results:
            return await upsert_food_from_external(session, off_results[0])

        # 5) FatSecret text search — gated by `settings.FATSECRET_ENABLED` so it
        #    stays in the codebase as a fallback we can flip on without
        #    re-plumbing the chain. `is_fatsecret_configured()` is the second
        #    gate; together they keep the chain valid in dev with no creds.
        if settings.FATSECRET_ENABLED:
            fs_query = f"{brand} {name}" if brand else name
            fs_results = await fs.search_foods_by_text(fs_query, limit=1)
            if fs_results:
                return await upsert_food_from_external(session, fs_results[0])

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
async def lookup_food(
    name: str,
    barcode: str | None = None,
    brand: str | None = None,
    strict: bool = False,
) -> FoodLookupResult:
    """Resolve a food's per-unit nutrition from the catalog or external sources.

    Order: local PG cache (barcode then name/alias) → Open Food Facts (barcode
    then brand-filtered text) → FatSecret (when `FATSECRET_ENABLED`). External
    hits are cached back into the catalog. Returns `found=False` when no source
    matches — call `estimate_food_nutrition` as the last resort.

    `strict=True` (used by the reflect-retry loop) skips fuzzy text search in
    OFF and FatSecret to avoid repeating the same bad branded match.
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
