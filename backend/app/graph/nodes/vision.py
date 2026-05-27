"""analyze_photo_node — GPT-4o Vision: items + built-in guiderail verdicts.

The vision call is the guiderail for the photo path: a single LLM call returns
`is_food_image` and `is_safe_image` alongside the parsed items. The graph
short-circuits to error_node when either flag is False (no second LLM call
just to gate the photo).
"""

from __future__ import annotations

import logging

from langsmith import traceable

from app.graph.state import GraphState
from app.services.openai_client import analyze_photo_meal

logger = logging.getLogger(__name__)


@traceable(run_type="chain", name="node_analyze_photo")
async def analyze_photo_node(state: GraphState) -> GraphState:
    images = state.get("photo_bytes_list") or []
    if not images:
        state["error"] = "no photo bytes in state"
        state["parsed_items"] = []
        state["is_input_safe"] = False
        state["guiderail_block_reason"] = "empty_photo"
        return state

    caption = state.get("caption") or None
    try:
        result = await analyze_photo_meal(images, caption=caption)
    except Exception as exc:
        logger.exception("Vision analysis failed")
        state["error"] = f"vision failed: {exc.__class__.__name__}"
        state["parsed_items"] = []
        state["is_input_safe"] = True  # not a guiderail block — infra error
        return state

    state["vision_scene"] = result.overall_description or ""

    if not result.is_safe_image:
        state["is_input_safe"] = False
        state["guiderail_block_reason"] = "unsafe"
        state["parsed_items"] = []
        return state

    if not result.is_food_image:
        state["is_input_safe"] = False
        state["guiderail_block_reason"] = "non_food"
        state["parsed_items"] = []
        return state

    state["is_input_safe"] = True
    state["parsed_items"] = list(result.items)
    state["is_food_related"] = bool(result.items)
    return state
