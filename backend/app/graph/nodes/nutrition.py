"""nutrition_fetch_node — resolve KBJU for parsed items via the Nutrition MCP.

For every parsed item this node fires a single MCP call —
`resolve_meal_item` — which runs the full pipeline server-side (catalog
lookup → LLM-estimate fallback → portion math) and returns absolute KBJU
ready to drop into a MealItem. The atomic tools (`lookup_food`,
`estimate_food_nutrition`, `compute_meal_item_nutrition`) stay registered on
the MCP server for external clients and unit tests, but the graph itself
makes one round-trip per item instead of three.

`reflect_strict` is propagated to the MCP tool but currently a no-op — kept
on the signature for the future when fuzzy external search returns and the
reflect-retry loop needs a way to disable it.
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
        state["error"] = "nothing resolved"
        return state

    strict = bool(state.get("reflect_strict"))

    # Resolve sequentially — items count is small (2-5/meal) and latency is
    # dominated by the external APIs behind the MCP tools, not local overhead.
    resolved: list[ResolvedItem] = []
    for item in items:
        r = await _resolve_one_item(item, strict=strict)
        if r is not None:
            resolved.append(r)

    state["resolved_items"] = resolved
    # Set the error tag here, not in the routing function — LangGraph drops
    # state mutations performed inside conditional-edge callbacks.
    if not resolved:
        state["error"] = "nothing resolved"
    return state


async def _resolve_one_item(
    item: ParsedFoodItem, *, strict: bool = False
) -> ResolvedItem | None:
    result = await call_mcp_tool(
        "resolve_meal_item",
        {
            "name": item.name,
            "amount": item.amount,
            "unit": item.unit.value,
            "brand": item.brand,
            "barcode": item.barcode,
            "strict": strict,
        },
    )
    if not result.get("found"):
        logger.warning(
            "Could not resolve food for '%s' (brand=%s) — %s",
            item.name,
            item.brand,
            result.get("reason") or "no match",
        )
        return None

    food_id = result.get("food_id")
    payload = MealItemPayload(
        food_name=result["food_name"],
        amount=item.amount,
        unit=item.unit,
        weight_g=result["weight_g"],
        kcal=result["kcal"],
        protein_g=result["protein_g"],
        fat_g=result["fat_g"],
        carbs_g=result["carbs_g"],
        food_id=UUID(food_id) if food_id else None,
    )
    return ResolvedItem(
        payload=payload,
        source=FoodSource(result["source"]),
        food_id_known=bool(food_id),
    )
