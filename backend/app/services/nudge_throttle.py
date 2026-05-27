"""Per-user nudge throttling — at most one follow-up every N hours."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

_MIN_INTERVAL = timedelta(hours=4)
_last_sent: dict[int, datetime] = {}
_lock = asyncio.Lock()


async def can_send_follow_up(telegram_user_id: int) -> bool:
    """Check whether a follow-up nudge for this user is allowed right now.

    Atomically marks the timestamp on success — so a second concurrent caller
    will get False (single-process only; multi-worker prod needs Redis).
    """
    now = datetime.now(timezone.utc)
    async with _lock:
        last = _last_sent.get(telegram_user_id)
        if last is not None and now - last < _MIN_INTERVAL:
            return False
        _last_sent[telegram_user_id] = now
    return True
