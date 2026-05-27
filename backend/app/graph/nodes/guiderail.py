"""guiderail_node — unified domain + safety check for text and voice paths.

Catches three classes of bad input before the text parser ever sees them:
  1. Inedible content disguised as food ("кал слона 100").
  2. Profanity / abuse with no food intent ("сука пиздец").
  3. Greetings / chit-chat that bypass the parser's keyword heuristic.

Implementation: two parallel calls — OpenAI Moderation API (covers explicit
hate / sexual / violence categories for free) and a tiny gpt-4o-mini
food-intent classifier (covers inedibles + nonsense which Moderation misses).

For the photo path, the guiderail is built into the vision call instead
(see `analyze_photo_node`) — one LLM call returns items + safety flags.
"""

from __future__ import annotations

import asyncio
import logging

from langsmith import traceable

from app.graph.state import GraphState
from app.services.openai_client import classify_food_intent, moderate_text

logger = logging.getLogger(__name__)


@traceable(run_type="chain", name="node_guiderail")
async def guiderail_node(state: GraphState) -> GraphState:
    text = (state.get("text_input") or state.get("transcribed_text") or "").strip()
    if not text:
        # Nothing to check — let the parser handle the empty-input error tag.
        state["is_input_safe"] = True
        return state

    try:
        is_flagged, intent = await asyncio.gather(
            moderate_text(text),
            classify_food_intent(text),
        )
    except Exception:
        # Infra blip — fail open: the parser still rejects clear inedibles.
        logger.exception("Guiderail failed — letting message through")
        state["is_input_safe"] = True
        return state

    if is_flagged:
        logger.info("Guiderail blocked: moderation flagged input")
        state["is_input_safe"] = False
        state["guiderail_block_reason"] = "unsafe"
        state["parsed_items"] = []
        state["is_food_related"] = False
        return state

    if not intent.is_food_intent:
        logger.info("Guiderail blocked: non-food intent (%s)", intent.category)
        state["is_input_safe"] = False
        state["guiderail_block_reason"] = (
            intent.category
        )  # greeting / abuse / inedible / nonsense
        state["parsed_items"] = []
        state["is_food_related"] = False
        return state

    state["is_input_safe"] = True
    return state
