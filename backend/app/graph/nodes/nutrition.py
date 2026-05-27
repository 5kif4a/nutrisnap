"""nutrition_fetch_node — multi-source lookup chain (local → OFF → FatSecret → estimate).

For every parsed item, resolves nutrition KBJU by trying sources in priority order
and computes the per-item nutrition payload using `compute_meal_item_nutrition`.
"""

from __future__ import annotations

import logging

from app.db.models import Food, FoodSource
from app.db.session import async_session_factory
from app.graph.state import GraphState, ResolvedItem
from app.repositories.food_repo import (
    lookup_food_by_barcode,
    search_foods_by_name,
    upsert_food_from_external,
)
from app.repositories.meal_repo import MealItemPayload
from app.services import fatsecret as fs
from app.services import openfoodfacts as off
from app.services.nutrition_calc import compute_meal_item_nutrition
from app.services.openai_client import ParsedFoodItem, estimate_nutrition

logger = logging.getLogger(__name__)


async def nutrition_fetch_node(state: GraphState) -> GraphState:
    items = state.get("parsed_items") or []
    if not items:
        state["resolved_items"] = []
        return state

    # AsyncSession is NOT concurrency-safe; resolve items sequentially.
    # Items count is typically 2-5 per meal, latency dominated by external APIs.
    resolved: list[ResolvedItem] = []
    async with async_session_factory() as session:
        for item in items:
            r = await _resolve_one_item(session, item)
            if r is not None:
                resolved.append(r)

    state["resolved_items"] = resolved
    return state


async def _resolve_one_item(session, item: ParsedFoodItem) -> ResolvedItem | None:
    food = await _resolve_food(session, item)
    if food is None:
        logger.warning("Could not resolve food for '%s' — skipping", item.name)
        return None

    try:
        nutrition = compute_meal_item_nutrition(food, item.amount, item.unit)
    except ValueError as exc:
        logger.warning("Cannot compute nutrition for %s: %s", item.name, exc)
        return None

    # Ephemeral (LLM-estimated) foods have no DB row — store the MealItem
    # snapshot with food_id=NULL so we never reference a non-existent row.
    food_persisted = food.id is not None
    payload = MealItemPayload(
        food_name=food.name,
        amount=item.amount,
        unit=item.unit,
        weight_g=nutrition.weight_g,
        kcal=nutrition.kcal,
        protein_g=nutrition.protein_g,
        fat_g=nutrition.fat_g,
        carbs_g=nutrition.carbs_g,
        food_id=food.id if food_persisted else None,
    )
    return ResolvedItem(
        payload=payload,
        source=food.source,
        food_id_known=food_persisted,
    )


async def _resolve_food(session, item: ParsedFoodItem) -> Food | None:
    """Try sources in priority order. Cache external hits into local PG."""
    # 1) Local cache by barcode if available
    if item.barcode:
        hit = await lookup_food_by_barcode(session, item.barcode)
        if hit is not None:
            return hit

    # 2) Local cache by name / aliases / brand
    local_hits = await search_foods_by_name(session, item.name, limit=1)
    if local_hits:
        return local_hits[0]

    # 3) Open Food Facts by barcode
    if item.barcode:
        off_hit = await off.lookup_food_by_barcode(item.barcode)
        if off_hit is not None:
            return await upsert_food_from_external(session, off_hit)

    # 4) Open Food Facts text search
    off_results = await off.search_foods_by_text(item.name, limit=1)
    if off_results:
        return await upsert_food_from_external(session, off_results[0])

    # 5) FatSecret text search — covers EN-only / branded items that OFF misses.
    # No-op (returns []) when credentials are not configured, so the chain
    # stays valid in dev without leaking errors.
    fs_results = await fs.search_foods_by_text(item.name, limit=1)
    if fs_results:
        return await upsert_food_from_external(session, fs_results[0])

    # 6) LLM estimate as last resort — ask gpt-4o-mini for typical KBJU.
    # NOTE: LLM estimates are intentionally NOT persisted to `foods`. Otherwise
    # a fake row (e.g. "шоколадка 100 ккал") would win subsequent local lookups
    # for similar-sounding queries and freeze that hallucination forever.
    # The ephemeral Food has id=None so the resulting MealItem is saved with
    # food_id=NULL (it's a snapshot — no foreign key into the catalog).
    estimate = await estimate_nutrition(item.name)
    return Food(
        name=estimate.name,
        aliases=[],
        brand=item.brand,
        barcode=item.barcode,
        metric=estimate.metric,
        kcal=estimate.kcal,
        protein_g=estimate.protein_g,
        fat_g=estimate.fat_g,
        carbs_g=estimate.carbs_g,
        piece_weight_g=estimate.piece_weight_g,
        servings=[],
        source=FoodSource.LLM_ESTIMATE,
    )
