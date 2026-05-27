"""`/recommend` command — RAG meal recommendations from the recommender graph."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db.models import FoodMetric, InputSource
from app.db.session import async_session_factory
from app.graph.recommender import RecommendedItem, get_recommender_graph
from app.repositories.meal_repo import MealItemPayload, log_meal_with_items
from app.repositories.user_repo import get_user_by_tg_id, upsert_user_from_telegram
from app.services.meal_type_inference import infer_meal_type_by_clock
from app.services.recommendation_cache import (
    get_recommendation,
    stash_recommendations,
)

logger = logging.getLogger(__name__)


async def handle_recommend_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User typed /recommend — produce 3 RAG-driven suggestions."""
    if update.effective_message is None or update.effective_user is None:
        return
    if not await _require_onboarded(update):
        return

    thinking = await update.effective_message.reply_text("🤔 Подбираю что съесть...")

    # Strip "/recommend" prefix to get a free-form query, if any.
    text = update.effective_message.text or ""
    freeform = text.partition(" ")[2].strip()

    state = {
        "telegram_user_id": update.effective_user.id,
        "intent": "freeform" if freeform else "deficit",
        "freeform_query": freeform,
    }

    try:
        graph = get_recommender_graph()
        result = await graph.ainvoke(state)
    except Exception as exc:
        logger.exception("Recommender graph failed")
        await thinking.edit_text(f"⚠️ Не получилось подобрать: {exc.__class__.__name__}")
        return

    if result.get("error"):
        await thinking.edit_text(f"⚠️ {result['error']}")
        return

    items: list[RecommendedItem] = result.get("recommendations") or []
    summary: str = result.get("summary") or ""

    if not items:
        await thinking.edit_text(
            summary
            or "Пока нечего рекомендовать — залогай пару приёмов и попробуй снова."
        )
        return

    token = await stash_recommendations(items)
    reply = _format_reply(summary, items)
    keyboard = _build_keyboard(token, items)
    await thinking.edit_text(reply, reply_markup=keyboard)


def _format_reply(summary: str, items: list[RecommendedItem]) -> str:
    lines: list[str] = []
    if summary:
        lines.append(summary)
        lines.append("")
    lines.append("🍽 *Рекомендую:*")
    for i, it in enumerate(items, 1):
        brand = f" *{it.brand}*" if it.brand else ""
        lines.append(
            f"{i}. {it.name}{brand} — {it.suggested_grams:g} г  "
            f"({it.kcal:.0f} ккал, Б {it.protein_g:.0f} / Ж {it.fat_g:.0f} / У {it.carbs_g:.0f})"
        )
        if it.rationale_short:
            lines.append(f"   _{it.rationale_short}_")
    return "\n".join(lines)


def _build_keyboard(token: str, items: list[RecommendedItem]) -> InlineKeyboardMarkup:
    rows = []
    for idx, it in enumerate(items):
        label = it.name if len(it.name) <= 22 else it.name[:21] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    f"+ {label} ({it.kcal:.0f} ккал)",
                    callback_data=f"radd:{token}:{idx}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


async def handle_recommend_add_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User tapped a recommendation — log it as a one-item Meal."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    try:
        _, token, idx_str = query.data.split(":", 2)
        idx = int(idx_str)
    except ValueError:
        await query.answer("⚠️ Неверный callback")
        return

    item = await get_recommendation(token, idx)
    if item is None:
        await query.answer("⏱ Рекомендация уже не активна", show_alert=True)
        return

    meal_type = infer_meal_type_by_clock()
    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, update.effective_user.id)
        if user is None:
            await query.answer("⚠️ Сначала /start")
            return
        payload = MealItemPayload(
            food_name=item.name,
            amount=item.suggested_grams,
            unit=FoodMetric.GRAMS,
            weight_g=item.suggested_grams,
            kcal=item.kcal,
            protein_g=item.protein_g,
            fat_g=item.fat_g,
            carbs_g=item.carbs_g,
            # food_id from the recommender is a string — convert in the
            # repository layer; here we leave as None to avoid an unknown-FK
            # commit failure on stale Qdrant points.
            food_id=None,
        )
        await log_meal_with_items(
            session,
            user=user,
            meal_type=meal_type,
            items=[payload],
            source=InputSource.QUICK_ADD,
        )

    await query.answer(f"✅ Записал «{item.name}»")


async def _require_onboarded(update: Update) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return False
    async with async_session_factory() as session:
        user = await upsert_user_from_telegram(session, update.effective_user)
    if user.is_onboarded:
        return True
    await update.effective_message.reply_text(
        "👋 Сначала /start — расчитаем твою норму КБЖУ"
    )
    return False
