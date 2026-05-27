"""nutrition_fetch_node — multi-source lookup chain (local → OFF → [FatSecret] → estimate).

For every parsed item, resolves nutrition KBJU by trying sources in priority order
and computes the per-item nutrition payload using `compute_meal_item_nutrition`.

FatSecret step is gated on `settings.FATSECRET_ENABLED` (default off) — kept in
the codebase as a fallback we can flip on without re-plumbing the chain.
"""

from __future__ import annotations

import logging

from langsmith import traceable

from app.core.config import settings
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


@traceable(run_type="chain", name="node_nutrition_lookup")
async def nutrition_fetch_node(state: GraphState) -> GraphState:
    items = state.get("parsed_items") or []
    if not items:
        state["resolved_items"] = []
        return state

    # `reflect` toggles this on retry: skip fuzzy OFF/FatSecret text matches
    # and lean on barcode + local PG + LLM-estimate path. Keeps obvious branded
    # mismatches (e.g. "Nuts 66" → wrong nut-butter row from OFF) from coming
    # back a second time.
    strict = bool(state.get("reflect_strict"))

    # AsyncSession is NOT concurrency-safe; resolve items sequentially.
    # Items count is typically 2-5 per meal, latency dominated by external APIs.
    resolved: list[ResolvedItem] = []
    async with async_session_factory() as session:
        for item in items:
            r = await _resolve_one_item(session, item, strict=strict)
            if r is not None:
                resolved.append(r)

    state["resolved_items"] = resolved
    return state


async def _resolve_one_item(
    session, item: ParsedFoodItem, *, strict: bool = False
) -> ResolvedItem | None:
    food = await _resolve_food(session, item, strict=strict)
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


async def _resolve_food(
    session, item: ParsedFoodItem, *, strict: bool = False
) -> Food | None:
    """Try sources in priority order. Cache external hits into local PG.

    In `strict` mode (used by reflect-retry) we skip fuzzy text search in OFF
    and FatSecret — those are the steps that produce the worst hallucinations
    ("Nuts 66" → some random nut-butter row). Barcode lookups stay (they're
    ground truth) and LLM-estimate stays (it's already plausibility-checked).
    """
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

    if not strict:
        # 4) Open Food Facts text search — pass brand so we hard-filter on it
        off_results = await off.search_foods_by_text(
            item.name, brand=item.brand, limit=1
        )
        if off_results:
            return await upsert_food_from_external(session, off_results[0])

        # 5) FatSecret text search — disabled by default (see settings.FATSECRET_ENABLED).
        # Kept gated so we can re-enable without re-plumbing the chain.
        if settings.FATSECRET_ENABLED:
            fs_query = f"{item.brand} {item.name}" if item.brand else item.name
            fs_results = await fs.search_foods_by_text(fs_query, limit=1)
            if fs_results:
                return await upsert_food_from_external(session, fs_results[0])

    # 6) LLM estimate — last resort, generic foods only.
    # For BRANDED items we refuse: the model doesn't know specific products
    # (e.g. "Maxler Ultra Whey") and confidently returns garbage like 12 kcal
    # for 30g whey. Better to skip the item than show absurd KBJU.
    if item.brand:
        logger.warning(
            "no external match for branded item '%s' (brand=%s); skipping llm_estimate",
            item.name,
            item.brand,
        )
        return None

    estimate = await estimate_nutrition(item.name)
    if not _is_nutrition_plausible(estimate):
        logger.warning(
            "llm_estimate macros implausible for '%s' (kcal=%s P=%s F=%s C=%s); skipping",
            item.name,
            estimate.kcal,
            estimate.protein_g,
            estimate.fat_g,
            estimate.carbs_g,
        )
        return None

    # NOTE: LLM estimates are intentionally NOT persisted to `foods`. Otherwise
    # a fake row (e.g. "шоколадка 100 ккал") would win subsequent local lookups
    # for similar-sounding queries and freeze that hallucination forever.
    # The ephemeral Food has id=None so the resulting MealItem is saved with
    # food_id=NULL (it's a snapshot — no foreign key into the catalog).
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


def _is_nutrition_plausible(est) -> bool:
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
