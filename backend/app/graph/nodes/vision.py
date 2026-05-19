"""analyze_photo_node — GPT-4o Vision analyses food photo."""

from __future__ import annotations

import logging

from app.graph.state import GraphState
from app.services.openai_client import analyze_photo_meal

logger = logging.getLogger(__name__)


async def analyze_photo_node(state: GraphState) -> GraphState:
    images = state.get("photo_bytes_list") or []
    if not images:
        state["error"] = "no photo bytes in state"
        state["parsed_items"] = []
        return state

    caption = state.get("caption") or None
    try:
        result = await analyze_photo_meal(images, caption=caption)
    except Exception as exc:
        logger.exception("Vision analysis failed")
        state["error"] = f"vision failed: {exc.__class__.__name__}"
        state["parsed_items"] = []
        return state

    state["parsed_items"] = list(result.items)
    state["is_food_related"] = bool(result.items)
    return state
