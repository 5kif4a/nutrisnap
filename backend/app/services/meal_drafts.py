"""In-memory cache of pending meal drafts awaiting user's meal-type choice.

When the graph resolves nutrition and returns to the bot, the bot shows an
inline keyboard "Breakfast / Lunch / Dinner / Snack". The user's tap fires a
callback with the draft id, which is then saved with the chosen meal_type.

Drafts are short-lived (minutes) — keeping them in process memory is fine.
For multi-worker prod we'd swap this for Redis or DB.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.db.models import InputSource
from app.repositories.meal_repo import MealItemPayload


@dataclass(slots=True)
class MealDraft:
    user_telegram_id: int
    items: list[MealItemPayload]
    source: InputSource
    raw_input: str | None
    tg_message_id: int | None
    eaten_at: datetime
    # Quick-add candidates shown alongside meal-type buttons. Each entry is a
    # ready-to-append MealItemPayload (food the user often eats at this time).
    # Indexed by their position in this list for the `qadd:<draft_id>:<idx>`
    # callback — keeps the callback payload under Telegram's 64-byte limit.
    quick_add_pool: list[MealItemPayload] = field(default_factory=list)
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=30)
    )


_drafts: dict[str, MealDraft] = {}
_lock = asyncio.Lock()


async def stash_draft(draft: MealDraft) -> str:
    """Store a draft and return a short opaque id for inline-callback round-trip."""
    draft_id = secrets.token_urlsafe(8)
    async with _lock:
        _drafts[draft_id] = draft
        _evict_expired_locked()
    return draft_id


async def pop_draft(draft_id: str) -> MealDraft | None:
    async with _lock:
        _evict_expired_locked()
        return _drafts.pop(draft_id, None)


async def peek_draft(draft_id: str) -> MealDraft | None:
    """Read a draft without removing it (used by quick-add callbacks)."""
    async with _lock:
        _evict_expired_locked()
        return _drafts.get(draft_id)


async def append_to_draft(draft_id: str, item: MealItemPayload) -> MealDraft | None:
    """Atomically append an item to the draft. Returns the updated draft or None
    if the draft has expired/been consumed."""
    async with _lock:
        _evict_expired_locked()
        draft = _drafts.get(draft_id)
        if draft is None:
            return None
        draft.items.append(item)
        return draft


def _evict_expired_locked() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _drafts.items() if v.expires_at <= now]
    for k in expired:
        del _drafts[k]
