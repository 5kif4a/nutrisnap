"""In-memory store for in-flight recipe-builder sessions.

Lifecycle per user:
    photo of ingredients on scale (single or album)
       ↓ user taps 🍳 "Сохранить как рецепт"
    RecipeDraft created from the existing MealDraft items
       ↓ COLLECTING — user may add more ingredient photos
       ↓ user taps ✅ "Готово"
       ↓ AWAIT_TOTAL_WEIGHT — user writes cooked weight in grams
       ↓ Food row persisted with per-100g macros (source=USER_RECIPE)
       ↓ AWAIT_PORTION — user writes how much they actually ate
       ↓ Meal row logged, draft cleared

One in-flight recipe per (telegram) user. Starting a new one cancels the
previous one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.repositories.meal_repo import MealItemPayload


@dataclass(slots=True)
class RecipeDraft:
    user_telegram_id: int
    chat_id: int
    name: str
    ingredients: list[MealItemPayload] = field(default_factory=list)
    # Set when the recipe-builder message bubble is created. We edit this one
    # message in place as ingredients accumulate so the chat stays clean.
    panel_message_id: int | None = None
    # Filled at the AWAIT_TOTAL_WEIGHT → save_recipe step.
    cooked_weight_g: float | None = None
    saved_food_id: str | None = None
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=2)
    )


_drafts: dict[int, RecipeDraft] = {}
_lock = asyncio.Lock()


async def put_draft(draft: RecipeDraft) -> None:
    """Replace any in-flight recipe for this user with the new one."""
    async with _lock:
        _drafts[draft.user_telegram_id] = draft


async def get_draft(user_telegram_id: int) -> RecipeDraft | None:
    async with _lock:
        draft = _drafts.get(user_telegram_id)
        if draft is None:
            return None
        if draft.expires_at <= datetime.now(timezone.utc):
            del _drafts[user_telegram_id]
            return None
        return draft


async def update_draft(user_telegram_id: int, **patch) -> RecipeDraft | None:
    async with _lock:
        draft = _drafts.get(user_telegram_id)
        if draft is None:
            return None
        for k, v in patch.items():
            setattr(draft, k, v)
        return draft


async def append_ingredients(
    user_telegram_id: int, items: list[MealItemPayload]
) -> RecipeDraft | None:
    async with _lock:
        draft = _drafts.get(user_telegram_id)
        if draft is None:
            return None
        draft.ingredients.extend(items)
        return draft


async def pop_draft(user_telegram_id: int) -> RecipeDraft | None:
    async with _lock:
        return _drafts.pop(user_telegram_id, None)
