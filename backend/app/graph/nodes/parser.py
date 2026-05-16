"""parse_text_node — turns free-form user text into structured ParsedFoodItem[]."""

from __future__ import annotations

import logging

from app.graph.state import GraphState
from app.services.openai_client import parse_text_meal

logger = logging.getLogger(__name__)


async def parse_text_node(state: GraphState) -> GraphState:
    text = (state.get("text_input") or state.get("transcribed_text") or "").strip()
    if not text:
        state["error"] = "empty text input"
        state["parsed_items"] = []
        state["is_food_related"] = False
        return state

    try:
        result = await parse_text_meal(text)
    except Exception as exc:
        logger.exception("Text parsing failed")
        state["error"] = f"parse failed: {exc.__class__.__name__}"
        state["parsed_items"] = []
        state["is_food_related"] = False
        return state

    state["parsed_items"] = list(result.items)
    state["is_food_related"] = result.is_food_related
    return state
