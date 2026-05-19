"""Buffer for Telegram media-group (album) photos.

Telegram delivers an album as N separate Update objects sharing a single
`media_group_id`. Processing each photo independently would yield N bot
replies for one user action. We instead:

  1. On the first photo of an mgid → start a new buffer + schedule a flush.
  2. On subsequent photos of the same mgid → append to the buffer.
  3. After a short debounce (`ALBUM_DEBOUNCE_SEC`) the flush coroutine drains
     the buffer and hands all photos to the meal graph as one batch.

This buffer also doubles as the foundation for the recipe-builder flow, where
the user takes one photo per weighed ingredient.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

ALBUM_DEBOUNCE_SEC = 1.5


@dataclass(slots=True)
class AlbumBuffer:
    chat_id: int
    first_tg_message_id: int
    photos: list[bytes] = field(default_factory=list)
    captions: list[str] = field(default_factory=list)
    thinking_msg_id: int | None = None


_buffers: dict[tuple[int, str], AlbumBuffer] = {}
_lock = asyncio.Lock()


async def append_photo(
    *,
    user_id: int,
    media_group_id: str,
    chat_id: int,
    tg_message_id: int,
    photo_bytes: bytes,
    caption: str,
) -> tuple[bool, AlbumBuffer]:
    """Add a photo to its album buffer.

    Returns `(is_first, buffer)`. The caller schedules the flush only when
    `is_first` is True so we don't double-schedule.
    """
    key = (user_id, media_group_id)
    async with _lock:
        is_first = key not in _buffers
        buffer = _buffers.setdefault(
            key,
            AlbumBuffer(chat_id=chat_id, first_tg_message_id=tg_message_id),
        )
        buffer.photos.append(photo_bytes)
        if caption:
            buffer.captions.append(caption)
        return is_first, buffer


async def attach_thinking_message(
    *, user_id: int, media_group_id: str, message_id: int
) -> None:
    key = (user_id, media_group_id)
    async with _lock:
        buffer = _buffers.get(key)
        if buffer is not None:
            buffer.thinking_msg_id = message_id


async def drain(*, user_id: int, media_group_id: str) -> AlbumBuffer | None:
    """Pop the buffer for this album — called once after the debounce."""
    key = (user_id, media_group_id)
    async with _lock:
        return _buffers.pop(key, None)
