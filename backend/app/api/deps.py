"""Mini App auth — verify Telegram WebApp `initData` and resolve the user.

Flow (see CLAUDE.md "Авторизация Mini App ↔ API"):
    Mini App sends raw initData in the `X-Init-Data` header on every request
    → we verify the HMAC-SHA256 signature with the bot token
    → extract `telegram_id` → get-or-create the user row.

In development (`ENV=development`) an empty header falls back to a fixed
fake user (telegram_id=999999) so the frontend can be run without Telegram.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.session import get_session
from app.repositories.user_repo import get_user_by_tg_id

# Dev-only fallback identity used when X-Init-Data is empty (browser testing).
# Set to the real Telegram id so the browser Mini App shows real bot data.
DEV_FAKE_TELEGRAM_ID = 339532463


def verify_init_data(init_data: str, bot_token: str) -> dict[str, str]:
    """Validate Telegram WebApp initData. Returns the parsed key/value pairs.

    Raises ValueError if the signature is missing or does not match.
    Algorithm: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise ValueError("init data has no hash")

    data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise ValueError("init data signature mismatch")
    return parsed


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    language_code: str | None = None,
) -> User:
    """Find a user by telegram_id, inserting a minimal row if absent."""
    user = await get_user_by_tg_id(session, telegram_id)
    if user is not None:
        return user

    stmt = (
        pg_insert(User)
        .values(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
        )
        .on_conflict_do_nothing(index_elements=["telegram_id"])
        .returning(User)
    )
    user = (await session.scalars(stmt)).one_or_none()
    await session.commit()
    if user is None:
        # Lost the insert race — the row exists now, re-read it.
        user = await get_user_by_tg_id(session, telegram_id)
    assert user is not None
    return user


async def get_current_user(
    x_init_data: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: authenticated NutriSnap user for the Mini App."""
    raw = (x_init_data or "").strip()

    if not raw:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing X-Init-Data header",
            )
        # Dev convenience — work without Telegram.
        return await get_or_create_user(
            session, DEV_FAKE_TELEGRAM_ID, first_name="Dev", username="dev"
        )

    try:
        parsed = verify_init_data(raw, settings.BOT_TOKEN)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid init data: {exc}",
        ) from exc

    user_json = parsed.get("user")
    if not user_json:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="init data has no user",
        )
    tg = json.loads(user_json)
    return await get_or_create_user(
        session,
        int(tg["id"]),
        username=tg.get("username"),
        first_name=tg.get("first_name"),
        language_code=tg.get("language_code"),
    )
