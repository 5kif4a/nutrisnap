"""Short-lived in-memory cache for `/recommend` results.

The bot sends 3 inline-buttons under each `/recommend` reply (one per item).
Telegram limits callback_data to 64 bytes, so we can't pack full nutrition
into the button itself. Instead each `/recommend` invocation stashes its
RecommendedItem list under a short token, and the button only carries
`radd:<token>:<idx>`.

Tokens auto-expire after 30 minutes — long enough for the user to scroll
back and tap, short enough that stale recommendations don't haunt the bot
when targets change.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from app.graph.recommender import RecommendedItem


_TTL = timedelta(minutes=30)
_cache: dict[str, tuple[list[RecommendedItem], datetime]] = {}
_lock = asyncio.Lock()


async def stash_recommendations(items: list[RecommendedItem]) -> str:
    """Store items and return an opaque short token for inline-button round-trip."""
    token = secrets.token_urlsafe(6)
    expires = datetime.now(timezone.utc) + _TTL
    async with _lock:
        _cache[token] = (items, expires)
        _evict_expired_locked()
    return token


async def get_recommendation(token: str, idx: int) -> RecommendedItem | None:
    async with _lock:
        _evict_expired_locked()
        entry = _cache.get(token)
        if entry is None:
            return None
        items, _ = entry
        if not 0 <= idx < len(items):
            return None
        return items[idx]


def _evict_expired_locked() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, (_, exp) in _cache.items() if exp <= now]
    for k in expired:
        del _cache[k]
