"""Meal input handlers — photo / voice / text → LangGraph → confirmation."""

from __future__ import annotations

import asyncio
import io
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import build_meal_type_keyboard
from app.db.models import InputSource, MealType
from app.db.session import async_session_factory
from app.graph.graph import get_meal_graph
from app.repositories.meal_repo import (
    MealItemPayload,
    log_meal_with_items,
)
from app.repositories.user_repo import (
    get_user_by_tg_id,
    upsert_user_from_telegram,
)
from app.services.meal_drafts import MealDraft, pop_draft, stash_draft
from app.services.meal_type_inference import infer_meal_type_by_clock
from app.services.photo_buffer import (
    ALBUM_DEBOUNCE_SEC,
    append_photo,
    attach_thinking_message,
    drain,
)

logger = logging.getLogger(__name__)


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None:
        return
    msg = update.effective_message
    if not msg.photo:
        return
    if not await _require_onboarded(update):
        return

    photo_bytes = await _download_largest_photo(msg)
    caption = msg.caption or ""

    if msg.media_group_id is None:
        # Single photo — process immediately.
        thinking = await msg.reply_text("🔍 Анализирую фото...")
        state = {
            "raw_input_type": "photo",
            "photo_bytes_list": [photo_bytes],
            "caption": caption,
            "telegram_user_id": update.effective_user.id,
            "tg_message_id": update.update_id,
        }
        await _run_graph_and_reply(update, context, state, thinking, source=InputSource.PHOTO)
        return

    # Album — buffer this photo. Only the first photo of a media_group
    # schedules the flush coroutine; subsequent photos just append.
    is_first, _ = await append_photo(
        user_id=update.effective_user.id,
        media_group_id=msg.media_group_id,
        chat_id=msg.chat_id,
        tg_message_id=update.update_id,
        photo_bytes=photo_bytes,
        caption=caption,
    )
    if not is_first:
        return

    thinking = await msg.reply_text("🔍 Анализирую альбом...")
    await attach_thinking_message(
        user_id=update.effective_user.id,
        media_group_id=msg.media_group_id,
        message_id=thinking.message_id,
    )
    asyncio.create_task(
        _flush_album_after_delay(
            context=context,
            user_id=update.effective_user.id,
            media_group_id=msg.media_group_id,
        )
    )


async def _download_largest_photo(msg) -> bytes:
    """Download the highest-resolution PhotoSize from a Telegram message."""
    photo = msg.photo[-1]
    photo_file = await photo.get_file()
    buf = io.BytesIO()
    await photo_file.download_to_memory(out=buf)
    return buf.getvalue()


async def _flush_album_after_delay(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    media_group_id: str,
) -> None:
    """Drain the album buffer after the debounce and feed the graph once."""
    await asyncio.sleep(ALBUM_DEBOUNCE_SEC)
    album = await drain(user_id=user_id, media_group_id=media_group_id)
    if album is None or not album.photos:
        return

    caption = " | ".join(album.captions) if album.captions else ""
    state = {
        "raw_input_type": "photo",
        "photo_bytes_list": album.photos,
        "caption": caption,
        "telegram_user_id": user_id,
        "tg_message_id": album.first_tg_message_id,
    }

    await _run_graph_and_post(
        context=context,
        telegram_user_id=user_id,
        chat_id=album.chat_id,
        thinking_msg_id=album.thinking_msg_id,
        state=state,
        source=InputSource.PHOTO,
        raw_input=caption or None,
        tg_message_id=album.first_tg_message_id,
    )


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None:
        return
    if not update.effective_message.voice:
        return
    if not await _require_onboarded(update):
        return

    thinking = await update.effective_message.reply_text("🎙 Транскрибирую...")

    voice = update.effective_message.voice
    voice_file = await voice.get_file()
    buffer = io.BytesIO()
    await voice_file.download_to_memory(out=buffer)

    state = {
        "raw_input_type": "voice",
        "voice_bytes": buffer.getvalue(),
        "voice_mime": voice.mime_type or "audio/ogg",
        "telegram_user_id": update.effective_user.id,
        "tg_message_id": update.update_id,
    }
    await _run_graph_and_reply(update, context, state, thinking, source=InputSource.VOICE)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None:
        return
    text = update.effective_message.text or ""
    if not text or text.startswith("/"):
        return
    if not await _require_onboarded(update):
        return

    is_forward = update.effective_message.forward_origin is not None

    thinking = await update.effective_message.reply_text("✏️ Обрабатываю...")

    state = {
        "raw_input_type": "forward" if is_forward else "text",
        "text_input": text,
        "telegram_user_id": update.effective_user.id,
        "tg_message_id": update.update_id,
    }
    await _run_graph_and_reply(update, context, state, thinking, source=InputSource.TEXT)


async def handle_save_meal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User tapped a meal-type button — persist the draft."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    try:
        _, draft_id, meal_type_value = query.data.split(":", 2)
    except ValueError:
        await query.edit_message_text("⚠️ Неверный callback")
        return

    draft = await pop_draft(draft_id)
    if draft is None:
        await query.edit_message_text("⏱ Этот черновик уже не действителен — отправь ещё раз.")
        return

    meal_type = MealType(meal_type_value)

    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, draft.user_telegram_id)
        if user is None:
            await query.edit_message_text("⚠️ Сначала /start")
            return
        meal = await log_meal_with_items(
            session,
            user=user,
            meal_type=meal_type,
            items=draft.items,
            eaten_at=draft.eaten_at,
            source=draft.source,
            raw_input=draft.raw_input,
            tg_message_id=draft.tg_message_id,
        )

    total_kcal = sum(it.kcal for it in meal.items)
    label = {
        MealType.BREAKFAST: "завтрак",
        MealType.LUNCH: "обед",
        MealType.DINNER: "ужин",
        MealType.SNACK: "перекус",
    }[meal_type]
    await query.edit_message_text(f"✅ Записано в {label}! +{total_kcal:.0f} ккал")


async def handle_cancel_meal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    try:
        _, draft_id = query.data.split(":", 1)
    except ValueError:
        await query.edit_message_text("⚠️ Неверный callback")
        return
    await pop_draft(draft_id)
    await query.edit_message_text("✖️ Отменено")


async def _require_onboarded(update: Update) -> bool:
    """Block meal input until the user has completed /start onboarding (has TDEE)."""
    if update.effective_user is None or update.effective_message is None:
        return False
    async with async_session_factory() as session:
        user = await upsert_user_from_telegram(session, update.effective_user)
    if user.is_onboarded:
        return True
    await update.effective_message.reply_text(
        "👋 Сначала давай рассчитаем твою суточную норму КБЖУ — нажми /start"
    )
    return False


async def _run_graph_and_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state: dict,
    thinking_message,
    *,
    source: InputSource,
) -> None:
    """Invoke the meal graph, stash draft, edit the 'thinking' bubble with result."""
    if update.effective_user is None or update.effective_message is None:
        return
    await _run_graph_and_post(
        context=context,
        telegram_user_id=update.effective_user.id,
        chat_id=thinking_message.chat_id,
        thinking_msg_id=thinking_message.message_id,
        state=state,
        source=source,
        raw_input=state.get("text_input") or state.get("caption") or None,
        tg_message_id=state.get("tg_message_id"),
    )


async def _run_graph_and_post(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_user_id: int,
    chat_id: int,
    thinking_msg_id: int | None,
    state: dict,
    source: InputSource,
    raw_input: str | None,
    tg_message_id: int | None,
) -> None:
    """Shared graph-runner. Edits a previously-sent thinking bubble with the result."""
    # Ensure the user exists in DB so we can attach the meal.
    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, telegram_user_id)
        if user is None:
            await _safe_edit(context, chat_id, thinking_msg_id, "⚠️ Сначала /start")
            return
        state.setdefault("user_id", str(user.id))

    try:
        graph = get_meal_graph()
        result = await graph.ainvoke(state)
    except Exception as exc:
        logger.exception("Graph invocation failed")
        await _safe_edit(
            context, chat_id, thinking_msg_id,
            f"⚠️ Ошибка обработки: {exc.__class__.__name__}",
        )
        return

    response_text = result.get("response_text", "(empty response)")
    resolved = result.get("resolved_items") or []

    if not resolved:
        await _safe_edit(context, chat_id, thinking_msg_id, response_text)
        return

    items: list[MealItemPayload] = [r["payload"] for r in resolved]
    draft = MealDraft(
        user_telegram_id=telegram_user_id,
        items=items,
        source=source,
        raw_input=raw_input,
        tg_message_id=tg_message_id,
        eaten_at=infer_meal_type_and_time(),
    )
    draft_id = await stash_draft(draft)

    keyboard = build_meal_type_keyboard(
        draft_id, with_recipe_option=(source == InputSource.PHOTO)
    )
    await _safe_edit(context, chat_id, thinking_msg_id, response_text, reply_markup=keyboard)


async def _safe_edit(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup=None,
) -> None:
    """Edit the thinking bubble, or send a new message if the id was lost."""
    if message_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, reply_markup=reply_markup,
            )
            return
        except Exception:
            logger.warning("edit_message_text failed; falling back to send", exc_info=True)
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


def infer_meal_type_and_time():
    """Right-now timestamp; meal type is decided when user taps the keyboard.

    Pre-computed inference is shown only as a hint (could be highlighted as
    the suggested button in the future).
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


__all__ = [
    "handle_photo_message",
    "handle_voice_message",
    "handle_text_message",
    "handle_save_meal_callback",
    "handle_cancel_meal_callback",
]


# Make F11 hint available for inspection/tests
_meal_type_inference = infer_meal_type_by_clock
