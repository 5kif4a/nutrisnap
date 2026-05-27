"""Meal input handlers — photo / voice / text → LangGraph → confirmation."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone

from langsmith import traceable
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.bot.keyboards import build_meal_type_keyboard
from app.db.models import InputSource, MealType
from app.db.session import async_session_factory
from app.graph.graph import get_meal_graph
from app.repositories.food_repo import (
    QuickAddItem,
    list_frequent_foods_per_meal_type,
    list_recent_foods_per_meal_type,
)
from app.repositories.meal_repo import (
    MealItemPayload,
    fetch_daily_summary,
    log_meal_with_items,
)
from app.repositories.user_repo import (
    get_user_by_tg_id,
    upsert_user_from_telegram,
)
from app.graph.recommender import get_recommender_graph
from app.services.meal_drafts import (
    MealDraft,
    append_to_draft,
    peek_draft,
    pop_draft,
    stash_draft,
)
from app.services.meal_type_inference import infer_meal_type_by_clock
from app.services.nudge_throttle import can_send_follow_up
from app.services.photo_buffer import (
    ALBUM_DEBOUNCE_SEC,
    append_photo,
    attach_thinking_message,
    drain,
)

logger = logging.getLogger(__name__)


@traceable(run_type="chain", name="meal_graph")
async def _invoke_meal_graph(state: dict) -> dict:
    """Single LangSmith parent run wrapping the full graph invocation.

    Each node already has its own `@traceable` so the LangSmith trace tree
    becomes: meal_graph → node_route → node_X → ... → node_finalize, with
    every LLM call nested under its node.
    """
    graph = get_meal_graph()
    return await graph.ainvoke(state)


async def handle_photo_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
        await _run_graph_and_reply(
            update, context, state, thinking, source=InputSource.PHOTO
        )
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


async def handle_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
    await _run_graph_and_reply(
        update, context, state, thinking, source=InputSource.VOICE
    )


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
    await _run_graph_and_reply(
        update, context, state, thinking, source=InputSource.TEXT
    )


async def handle_save_meal_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
        await query.edit_message_text(
            "⏱ Этот черновик уже не действителен — отправь ещё раз."
        )
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
        # Re-aggregate the whole day AFTER this meal is persisted so the user
        # sees their up-to-date progress vs daily targets in the same message.
        day_summary = await fetch_daily_summary(
            session, user, summary_date=meal.eaten_at.date()
        )

    await query.edit_message_text(
        _render_meal_confirmation(meal, meal_type, day_summary)
    )

    # Post-meal follow-up — see _maybe_send_follow_up for trigger conditions.
    asyncio.create_task(
        _maybe_send_follow_up(
            context=context,
            chat_id=query.message.chat_id if query.message else None,
            telegram_user_id=draft.user_telegram_id,
            meal_kcal=sum(it.kcal for it in meal.items),
            meal_eaten_at=meal.eaten_at,
        )
    )


async def _maybe_send_follow_up(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int | None,
    telegram_user_id: int,
    meal_kcal: float,
    meal_eaten_at: datetime,
) -> None:
    """Fire a short LLM-driven follow-up after a meal save, but only when
    the meal was either large (>700 kcal) or late in the day (≥19:00).

    Throttled to once per 4 hours per user. Fully fire-and-forget — any
    failure is logged and swallowed so it never blocks the save reply.
    """
    if chat_id is None:
        return
    if meal_kcal < 700 and meal_eaten_at.hour < 19:
        return  # not "big" enough and not "late" enough
    if not await can_send_follow_up(telegram_user_id):
        return

    try:
        graph = get_recommender_graph()
        result = await graph.ainvoke(
            {
                "telegram_user_id": telegram_user_id,
                "intent": "deficit",
                "freeform_query": "",
            }
        )
    except Exception:
        logger.exception("Follow-up recommender failed for user %s", telegram_user_id)
        return

    items = result.get("recommendations") or []
    if not items:
        return

    pick = items[0]  # one item is enough as a nudge — don't spam
    brand = f" *{pick.brand}*" if pick.brand else ""
    text = (
        f"💡 Если ещё захочешь добрать норму — попробуй {pick.name}{brand} "
        f"({pick.suggested_grams:g} г, {pick.kcal:.0f} ккал)."
    )
    if pick.rationale_short:
        text += f"\n_{pick.rationale_short}_"

    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except TelegramError:
        logger.exception("Follow-up send failed for user %s", telegram_user_id)


async def handle_quick_add_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User tapped a quick-add suggestion — append it to the draft and re-render."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    try:
        _, draft_id, idx_str = query.data.split(":", 2)
        idx = int(idx_str)
    except ValueError:
        await query.answer("⚠️ Неверный callback")
        return

    draft = await peek_draft(draft_id)
    if draft is None:
        await query.answer("⏱ Черновик уже не активен", show_alert=True)
        return
    if not 0 <= idx < len(draft.quick_add_pool):
        await query.answer("⚠️ Этот вариант больше недоступен")
        return

    item = draft.quick_add_pool[idx]
    updated = await append_to_draft(draft_id, item)
    if updated is None:
        await query.answer("⏱ Черновик истёк")
        return

    await query.answer(f"+ {item.food_name}")

    # Re-render the confirmation message with the new totals; drop the just-added
    # item from the quick-add pool so it doesn't show up twice.
    updated.quick_add_pool = [
        q for q in updated.quick_add_pool if q.food_name != item.food_name
    ]
    response_text = _render_draft_summary(updated)
    keyboard = build_meal_type_keyboard(
        draft_id,
        with_recipe_option=(updated.source == InputSource.PHOTO),
        quick_add_pool=updated.quick_add_pool,
    )
    if query.message is not None:
        await _safe_edit(
            context,
            query.message.chat_id,
            query.message.message_id,
            response_text,
            reply_markup=keyboard,
        )


_MEAL_TYPE_LABELS_RU: dict[MealType, str] = {
    MealType.BREAKFAST: "завтрак",
    MealType.LUNCH: "обед",
    MealType.DINNER: "ужин",
    MealType.SNACK: "перекус",
}


def _render_meal_confirmation(meal, meal_type: MealType, day) -> str:
    """Post-save confirmation: delta added + daily progress vs targets.

    `meal` is the persisted Meal (with loaded `items`), `day` is the
    DailySummary aggregated over all of meal.eaten_at's UTC day.
    """
    label = _MEAL_TYPE_LABELS_RU[meal_type]

    delta_kcal = sum(it.kcal for it in meal.items)
    delta_p = sum(it.protein_g for it in meal.items)
    delta_f = sum(it.fat_g for it in meal.items)
    delta_c = sum(it.carbs_g for it in meal.items)

    food_names = ", ".join(it.food_name for it in meal.items)

    lines = [
        f"✅ Записано в {label}",
        "",
        f"🍽 {food_names}",
        f"+ {delta_kcal:.0f} ккал · Б {delta_p:.0f} / Ж {delta_f:.0f} / У {delta_c:.0f}",
        "",
        "📊 За день:",
    ]

    # Targets may be missing if onboarding was skipped — fall back to "—".
    if day.target_kcal:
        pct = day.total_kcal / day.target_kcal * 100
        lines.append(
            f"• {day.total_kcal:.0f} / {day.target_kcal} ккал ({pct:.0f}% РСК)"
        )
    else:
        lines.append(f"• {day.total_kcal:.0f} ккал")

    lines.append(f"• Б {day.total_protein_g:.0f} / {day.target_protein_g or '—'} г")
    lines.append(f"• Ж {day.total_fat_g:.0f} / {day.target_fat_g or '—'} г")
    lines.append(f"• У {day.total_carbs_g:.0f} / {day.target_carbs_g or '—'} г")

    return "\n".join(lines)


def _render_draft_summary(draft: MealDraft) -> str:
    """Re-build the '📋 Распознал' summary from the current draft items."""
    lines = ["📋 Распознал:"]
    total_kcal = 0.0
    total_p = 0.0
    total_f = 0.0
    total_c = 0.0
    for p in draft.items:
        lines.append(
            f"• {p.food_name} — {p.amount:g} {p.unit.value} "
            f"({p.kcal:.0f} ккал, Б {p.protein_g:.0f} / Ж {p.fat_g:.0f} / У {p.carbs_g:.0f})"
        )
        total_kcal += p.kcal
        total_p += p.protein_g
        total_f += p.fat_g
        total_c += p.carbs_g
    lines.append("")
    lines.append(
        f"Итого: {total_kcal:.0f} ккал | Б {total_p:.0f} / Ж {total_f:.0f} / У {total_c:.0f}"
    )
    lines.append("")
    lines.append("Куда записать?")
    return "\n".join(lines)


async def handle_cancel_meal_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
        result = await _invoke_meal_graph(state)
    except Exception:
        # Real class name goes to logs / LangSmith; the user sees a friendly
        # generic message instead of "InternalServerError: 500" gibberish.
        logger.exception("Graph invocation failed")
        await _safe_edit(
            context,
            chat_id,
            thinking_msg_id,
            "🙃 Что-то пошло не так. Попробуй ещё раз через минуту — "
            "если повторится, пришли тот же приём другим способом "
            "(фото / голос / текст).",
        )
        return

    response_text = result.get("response_text", "(empty response)")
    resolved = result.get("resolved_items") or []

    if not resolved:
        await _safe_edit(context, chat_id, thinking_msg_id, response_text)
        return

    items: list[MealItemPayload] = [r["payload"] for r in resolved]
    quick_add_pool = await _build_quick_add_pool(
        telegram_user_id, exclude_food_names={it.food_name for it in items}
    )
    draft = MealDraft(
        user_telegram_id=telegram_user_id,
        items=items,
        source=source,
        raw_input=raw_input,
        tg_message_id=tg_message_id,
        eaten_at=infer_meal_type_and_time(),
        quick_add_pool=quick_add_pool,
    )
    draft_id = await stash_draft(draft)

    keyboard = build_meal_type_keyboard(
        draft_id,
        with_recipe_option=(source == InputSource.PHOTO),
        quick_add_pool=quick_add_pool,
    )
    await _safe_edit(
        context, chat_id, thinking_msg_id, response_text, reply_markup=keyboard
    )


async def _build_quick_add_pool(
    telegram_user_id: int, *, exclude_food_names: set[str]
) -> list[MealItemPayload]:
    """Pull the user's frequent foods for this time-of-day → MealItemPayload list.

    Falls back to plain recents if the user has too little history for the
    `frequent` query (which needs count>=2 per food in the last 30 days).
    Excludes anything already in the current draft so we don't suggest
    duplicates of what was just recognised.
    """
    meal_type = infer_meal_type_by_clock()
    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, telegram_user_id)
        if user is None:
            return []
        candidates: list[QuickAddItem] = await list_frequent_foods_per_meal_type(
            session, user, meal_type, limit=8
        )
        if len(candidates) < 4:
            candidates = await list_recent_foods_per_meal_type(
                session, user, meal_type, limit=8
            )

    excluded = {n.lower() for n in exclude_food_names}
    pool: list[MealItemPayload] = []
    seen: set[str] = set()
    for c in candidates:
        key = c.food_name.lower()
        if key in excluded or key in seen:
            continue
        seen.add(key)
        pool.append(
            MealItemPayload(
                food_name=c.food_name,
                amount=c.amount,
                unit=c.unit,
                weight_g=c.weight_g,
                kcal=c.kcal,
                protein_g=c.protein_g,
                fat_g=c.fat_g,
                carbs_g=c.carbs_g,
                food_id=c.food_id,
            )
        )
        if len(pool) >= 4:
            break
    return pool


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
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            logger.warning(
                "edit_message_text failed; falling back to send", exc_info=True
            )
    await context.bot.send_message(
        chat_id=chat_id, text=text, reply_markup=reply_markup
    )


def infer_meal_type_and_time():
    """Right-now timestamp; meal type is decided when user taps the keyboard.

    Pre-computed inference is shown only as a hint (could be highlighted as
    the suggested button in the future).
    """
    return datetime.now(timezone.utc)


__all__ = [
    "handle_photo_message",
    "handle_voice_message",
    "handle_text_message",
    "handle_quick_add_callback",
    "handle_save_meal_callback",
    "handle_cancel_meal_callback",
]


# Make F11 hint available for inspection/tests
_meal_type_inference = infer_meal_type_by_clock
