"""parse_text_node — turns free-form user text into structured ParsedFoodItem[]."""

from __future__ import annotations

import logging

from langsmith import traceable

from app.graph.state import GraphState
from app.services.openai_client import parse_text_meal

logger = logging.getLogger(__name__)

# Heuristic used when the LLM returns no items. If the message looks like a
# greeting / help-request with no food-related tokens, treat as non-food so
# the bot can answer "🥦 я только про еду" instead of "не смог распознать".
_NON_FOOD_KEYWORDS = (
    "привет",
    "здарова",
    "здравствуй",
    "добрый день",
    "добрый вечер",
    "доброе утро",
    "hi",
    "hello",
    "hey",
    "спасибо",
    "thanks",
    "thank you",
    "пока",
    "до свидания",
    "до встречи",
    "что ты",
    "что умеешь",
    "что такое",
    "как работаешь",
    "помоги",
    "помощь",
    "help",
    "/start",
    "/help",
    "/menu",
)


def _looks_like_non_food(text: str) -> bool:
    """True only for messages clearly NOT about food (greetings, help, etc.).

    Heuristic: lowercase text must start with one of the keyword phrases AND
    contain no digits (digits implies a portion → user logged something).
    """
    if any(ch.isdigit() for ch in text):
        return False
    lower = text.lower().lstrip()
    return any(lower.startswith(kw) for kw in _NON_FOOD_KEYWORDS)


@traceable(run_type="chain", name="node_parse_text")
async def parse_text_node(state: GraphState) -> GraphState:
    text = (state.get("text_input") or state.get("transcribed_text") or "").strip()
    if not text:
        state["error"] = "empty text input"
        state["parsed_items"] = []
        state["is_food_related"] = False
        return state

    # Short-circuit on obvious non-food before paying for an LLM call.
    if _looks_like_non_food(text):
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

    items = list(result.items)
    state["parsed_items"] = items
    # The LLM no longer returns is_food_related — we derive it here.
    # Logic: items found → food. No items + clearly non-food text → not food.
    # No items + ambiguous text → still food (user might have typed something
    # we couldn't parse), so the bot says "couldn't recognize" instead of
    # "I'm only for diary" — better UX for parsing fails.
    state["is_food_related"] = bool(items) or not _looks_like_non_food(text)
    return state
