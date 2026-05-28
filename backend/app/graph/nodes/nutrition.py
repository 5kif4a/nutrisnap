"""nutrition_fetch_node — resolve KBJU for parsed items via the Nutrition MCP.

For every parsed item this node calls the custom Nutrition MCP server's tools
(over the MCP protocol, see `app.mcp`) rather than the repositories directly:

    lookup_food → (if not found) estimate_food_nutrition → compute_meal_item_nutrition

The MCP tools own the source-priority chain, the FatSecret/strict gating and the
LLM-fallback policy (branded-item refusal + Atwater plausibility); this node just
orchestrates the tools, propagates `reflect_strict` for the reflect-retry loop,
and shapes the result into a MealItem snapshot.
"""

from __future__ import annotations

import logging
from uuid import UUID

from langsmith import traceable

from app.db.models import FoodSource
from app.graph.state import GraphState, ResolvedItem
from app.mcp.client import call_mcp_tool
from app.repositories.meal_repo import MealItemPayload
from app.services.openai_client import ParsedFoodItem

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
    # back a second time. The MCP `lookup_food` tool honours this flag.
    strict = bool(state.get("reflect_strict"))

    # Resolve sequentially — items count is small (2-5/meal) and latency is
    # dominated by the external APIs behind the MCP tools, not local overhead.
    resolved: list[ResolvedItem] = []
    for item in items:
        r = await _resolve_one_item(item, strict=strict)
        if r is not None:
            resolved.append(r)

    state["resolved_items"] = resolved
    return state


async def _resolve_one_item(
    item: ParsedFoodItem, *, strict: bool = False
) -> ResolvedItem | None:
    food = await call_mcp_tool(
        "lookup_food",
        {
            "name": item.name,
            "barcode": item.barcode,
            "brand": item.brand,
            "strict": strict,
        },
    )
    if not food.get("found"):
        # No source matched — try the LLM estimate tool (ephemeral). The tool
        # refuses branded items and rejects implausible macros itself, so a
        # `found=False` here is a real "skip this item" signal.
        food = await call_mcp_tool(
            "estimate_food_nutrition", {"name": item.name, "brand": item.brand}
        )
        if not food.get("found"):
            logger.warning(
                "Could not resolve food for '%s' (brand=%s) — %s",
                item.name,
                item.brand,
                food.get("reason") or "no match",
            )
            return None

    nutrition = await call_mcp_tool(
        "compute_meal_item_nutrition",
        {
            "metric": food["metric"],
            "kcal": food["kcal"],
            "protein_g": food["protein_g"],
            "fat_g": food["fat_g"],
            "carbs_g": food["carbs_g"],
            "piece_weight_g": food.get("piece_weight_g"),
            "amount": item.amount,
            "unit": item.unit.value,
        },
    )
    if not nutrition.get("ok"):
        logger.warning(
            "Cannot compute nutrition for %s: %s", item.name, nutrition.get("error")
        )
        return None

    # Ephemeral (LLM-estimated) foods have food_id=None — store the MealItem
    # snapshot with food_id=NULL so we never reference a non-existent row.
    food_id = food.get("food_id")
    payload = MealItemPayload(
        food_name=food["name"],
        amount=item.amount,
        unit=item.unit,
        weight_g=nutrition["weight_g"],
        kcal=nutrition["kcal"],
        protein_g=nutrition["protein_g"],
        fat_g=nutrition["fat_g"],
        carbs_g=nutrition["carbs_g"],
        food_id=UUID(food_id) if food_id else None,
    )
    return ResolvedItem(
        payload=payload,
        source=FoodSource(food["source"]),
        food_id_known=bool(food_id),
    )
