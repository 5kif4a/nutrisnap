"""GraphState — the shared mutable context passed between LangGraph nodes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from app.db.models import FoodSource, MealType
from app.repositories.meal_repo import MealItemPayload
from app.services.openai_client import ParsedFoodItem


InputType = Literal["photo", "voice", "text", "forward", "unknown"]


class ResolvedItem(TypedDict, total=False):
    """A parsed item enriched with nutrition data, ready to save as a MealItem."""
    payload: MealItemPayload
    source: FoodSource          # where nutrition came from
    food_id_known: bool         # True if we matched to a Food in PG cache


class GraphState(TypedDict, total=False):
    """Mutable state that flows through every node in the LangGraph workflow."""

    # ─── Input (set by caller before invoke) ─────────────────────────────
    telegram_user_id: int
    user_id: str                 # internal UUID (str form for serialization)
    raw_input_type: InputType
    # Always a list. Single-photo case populates a one-element list; albums
    # (Telegram media_group_id) populate all photos for unified vision parsing.
    photo_bytes_list: list[bytes]
    voice_bytes: bytes
    voice_mime: str
    text_input: str
    caption: str
    forward_date: datetime
    tg_message_id: int
    suggested_meal_type: MealType  # inferred or user-chosen

    # ─── Intermediate (filled by nodes) ──────────────────────────────────
    transcribed_text: str
    parsed_items: list[ParsedFoodItem]
    is_food_related: bool
    detected_barcode: str

    # ─── Output ──────────────────────────────────────────────────────────
    resolved_items: list[ResolvedItem]
    response_text: str           # human-friendly summary for the bot to send
    error: str
