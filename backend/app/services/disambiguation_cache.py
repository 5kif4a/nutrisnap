"""Short-lived in-memory stash for food disambiguation state.

When the bot finds ≥2 close Qdrant candidates for a user's query it shows
inline buttons instead of immediately showing the meal-type keyboard.  The
chosen candidate + original parsed amount are stored here so the callback
handler can compute portion nutrition and build the final draft.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.db.models import InputSource


@dataclass(slots=True)
class DisambiguationEntry:
    """Everything needed to build a MealDraft once the user picks a food."""

    candidates: list[dict]  # FoodCandidate dicts from Qdrant payload
    amount: float
    unit: str  # FoodMetric value ("g", "ml", "piece", "serving")
    user_telegram_id: int
    source: InputSource
    raw_input: str | None
    tg_message_id: int | None
    eaten_at: datetime
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=15)
    )


_TTL = timedelta(minutes=15)
_cache: dict[str, DisambiguationEntry] = {}
_lock = asyncio.Lock()


async def stash_disambiguation(entry: DisambiguationEntry) -> str:
    token = secrets.token_urlsafe(6)
    async with _lock:
        _cache[token] = entry
        _evict_expired_locked()
    return token


async def pop_disambiguation(token: str) -> DisambiguationEntry | None:
    async with _lock:
        _evict_expired_locked()
        return _cache.pop(token, None)


def _evict_expired_locked() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _cache.items() if v.expires_at <= now]
    for k in expired:
        del _cache[k]
