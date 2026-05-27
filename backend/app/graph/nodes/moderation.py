"""moderate_input_node — input safety gate that runs before the text parser.

Catches three classes of bad input that the meal parser would otherwise happily
turn into Food rows:
  1. Inedible content disguised as food (e.g. "кал слона 100").
  2. Profanity / abuse with no food intent (e.g. "сука пиздец").
  3. Greetings / chit-chat (e.g. "что умеешь") — already handled cheaply by
     the parser's keyword heuristic, but the LLM gate is the robust fallback
     for adversarial inputs that try to bypass simple string matching.

Implementation: two parallel calls — OpenAI Moderation API (covers explicit
hate / sexual / violence categories for free) and a tiny gpt-4o-mini
food-intent classifier (covers inedibles + nonsense which Moderation misses).
"""

from __future__ import annotations

import asyncio
import logging

from app.graph.state import GraphState
from app.services.openai_client import classify_food_intent, moderate_text

logger = logging.getLogger(__name__)


async def moderate_input_node(state: GraphState) -> GraphState:
    text = (state.get("text_input") or state.get("transcribed_text") or "").strip()
    if not text:
        return state

    try:
        is_flagged, intent = await asyncio.gather(
            moderate_text(text),
            classify_food_intent(text),
        )
    except Exception:
        logger.exception("Moderation gate failed — letting message through")
        return state

    if is_flagged or not intent.is_food_intent:
        logger.info(
            "Blocked input by moderation gate: flagged=%s category=%s",
            is_flagged,
            intent.category,
        )
        state["is_food_related"] = False
        state["parsed_items"] = []
    return state
