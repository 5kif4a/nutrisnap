"""/calculate — KBJU calculator for a custom dish from ingredient list.

The user types (or forwards) one or more messages with ingredients + weights.
Each message is parsed through the graph and accumulated in a live panel.
On "Готово" the bot shows per-100g breakdown and optionally saves the dish
to the user's food catalog so future logs can reference it by name.

This ConversationHandler runs BEFORE the generic text handler, so forwarded
ingredient lists are captured here and not processed as standalone meal logs.

States
------
COLLECTING : user is adding ingredients; panel stays live
NAMING     : user types the dish name; then confirms save / skip
"""

from __future__ import annotations

import logging
from enum import IntEnum

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.db.session import async_session_factory
from app.graph.graph import get_meal_graph
from app.repositories.food_repo import save_user_recipe
from app.repositories.meal_repo import MealItemPayload
from app.repositories.user_repo import get_user_by_tg_id

logger = logging.getLogger(__name__)


class _Step(IntEnum):
    COLLECTING = 20
    NAMING = 21


_KEY_ITEMS = "calc_items"
_KEY_NAME = "calc_dish_name"
_KEY_PANEL_MSG_ID = "calc_panel_msg_id"
_KEY_PANEL_CHAT_ID = "calc_panel_chat_id"

_DONE_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("✅ Готово — посчитать", callback_data="calc:done")],
        [InlineKeyboardButton("✖️ Отмена", callback_data="calc:cancel")],
    ]
)
_SAVE_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("💾 Сохранить в базу", callback_data="calc:save")],
        [InlineKeyboardButton("✅ Только посчитать", callback_data="calc:skip")],
    ]
)


# ─── Entry ────────────────────────────────────────────────────────────────────


async def handle_calculate_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None or update.effective_user is None:
        return ConversationHandler.END

    context.user_data[_KEY_ITEMS] = []
    context.user_data.pop(_KEY_NAME, None)
    context.user_data.pop(_KEY_PANEL_MSG_ID, None)
    context.user_data.pop(_KEY_PANEL_CHAT_ID, None)

    panel: Message = await update.effective_message.reply_text(
        _render_panel([]),
        parse_mode="Markdown",
        reply_markup=_DONE_KEYBOARD,
    )
    context.user_data[_KEY_PANEL_MSG_ID] = panel.message_id
    context.user_data[_KEY_PANEL_CHAT_ID] = panel.chat_id
    return _Step.COLLECTING


# ─── COLLECTING ───────────────────────────────────────────────────────────────


async def handle_calc_ingredient_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None or update.effective_user is None:
        return _Step.COLLECTING

    text = (update.effective_message.text or "").strip()
    if not text:
        return _Step.COLLECTING

    thinking = await update.effective_message.reply_text("⏳ Парсю...")

    state = {
        "raw_input_type": "text",
        "text_input": text,
        "telegram_user_id": update.effective_user.id,
        "tg_message_id": update.update_id,
    }

    try:
        graph = get_meal_graph()
        result = await graph.ainvoke(state)
    except Exception:
        logger.exception("Calculate graph invocation failed")
        await thinking.edit_text("⚠️ Не смог разобрать. Попробуй написать по-другому.")
        return _Step.COLLECTING

    resolved = result.get("resolved_items") or []
    if not resolved:
        await thinking.edit_text(
            result.get("response_text")
            or "Не смог распознать продукты. Пример: «курица 300»"
        )
        return _Step.COLLECTING

    new_items: list[MealItemPayload] = [r["payload"] for r in resolved]
    calc_items: list[MealItemPayload] = context.user_data.get(_KEY_ITEMS) or []
    calc_items.extend(new_items)
    context.user_data[_KEY_ITEMS] = calc_items

    added = ", ".join(f"{it.food_name} {it.amount:g}{it.unit}" for it in new_items)
    await thinking.edit_text(f"✅ {added}")

    await _refresh_panel(context, calc_items)
    return _Step.COLLECTING


async def handle_calc_done_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return _Step.COLLECTING
    await query.answer()

    calc_items: list[MealItemPayload] = context.user_data.get(_KEY_ITEMS) or []
    if not calc_items:
        await query.answer("❌ Добавь хотя бы один ингредиент", show_alert=True)
        return _Step.COLLECTING

    totals = _sum_macros(calc_items)
    total_weight = sum(it.weight_g for it in calc_items)

    lines = ["📋 *Состав блюда:*"]
    for it in calc_items:
        lines.append(
            f"• {it.food_name} — {it.amount:g} {it.unit} ({it.kcal:.0f} ккал)"
        )
    lines.append("")
    lines.append(f"⚖️ Вес ингредиентов: *{total_weight:.0f} г*")
    lines.append(
        f"🔥 Итого: *{totals['kcal']:.0f} ккал* | "
        f"Б *{totals['protein_g']:.0f}* / Ж *{totals['fat_g']:.0f}* / У *{totals['carbs_g']:.0f}* г"
    )
    if total_weight > 0:
        p = {k: v / total_weight * 100 for k, v in totals.items()}
        lines.append("")
        lines.append(
            f"На 100 г: *{p['kcal']:.0f} ккал* | "
            f"Б {p['protein_g']:.1f} / Ж {p['fat_g']:.1f} / У {p['carbs_g']:.1f} г"
        )
    lines.append("")
    lines.append("📝 Как назвать это блюдо?")

    # Collapse the panel into the summary (no more add buttons).
    panel_msg_id = context.user_data.get(_KEY_PANEL_MSG_ID)
    panel_chat_id = context.user_data.get(_KEY_PANEL_CHAT_ID)
    if panel_msg_id and panel_chat_id:
        try:
            await context.bot.edit_message_text(
                chat_id=panel_chat_id,
                message_id=panel_msg_id,
                text="\n".join(lines),
                parse_mode="Markdown",
            )
        except Exception:
            logger.debug("Could not collapse panel", exc_info=True)
    return _Step.NAMING


# ─── NAMING ───────────────────────────────────────────────────────────────────


async def handle_calc_name_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None:
        return _Step.NAMING

    name = (update.effective_message.text or "").strip()
    if not name:
        return _Step.NAMING

    context.user_data[_KEY_NAME] = name

    calc_items: list[MealItemPayload] = context.user_data.get(_KEY_ITEMS) or []
    totals = _sum_macros(calc_items)
    total_weight = sum(it.weight_g for it in calc_items)
    per100 = (
        {k: v / total_weight * 100 for k, v in totals.items()}
        if total_weight > 0
        else totals
    )

    await update.effective_message.reply_text(
        f"🍽 *{name}*\n\n"
        f"На 100 г: *{per100['kcal']:.0f} ккал*\n"
        f"Б {per100['protein_g']:.1f} г | Ж {per100['fat_g']:.1f} г | У {per100['carbs_g']:.1f} г\n\n"
        f"Всего: {totals['kcal']:.0f} ккал · {total_weight:.0f} г\n\n"
        "Сохранить блюдо в свою базу?\n"
        "_После сохранения пиши «150 г имя» — сразу залогирую без пересчёта._",
        parse_mode="Markdown",
        reply_markup=_SAVE_KEYBOARD,
    )
    return _Step.NAMING


async def handle_calc_save_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()

    calc_items: list[MealItemPayload] = context.user_data.get(_KEY_ITEMS) or []
    name: str = context.user_data.get(_KEY_NAME) or "Моё блюдо"
    total_weight = sum(it.weight_g for it in calc_items)

    if not calc_items or total_weight <= 0:
        await query.edit_message_text("⚠️ Нет данных для сохранения.")
        _clear_state(context)
        return ConversationHandler.END

    totals = _sum_macros(calc_items)

    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, update.effective_user.id)
        if user is None:
            await query.edit_message_text("⚠️ Сначала /start")
            _clear_state(context)
            return ConversationHandler.END
        food = await save_user_recipe(
            session,
            user=user,
            name=name,
            ingredients_total_kcal=totals["kcal"],
            ingredients_total_protein_g=totals["protein_g"],
            ingredients_total_fat_g=totals["fat_g"],
            ingredients_total_carbs_g=totals["carbs_g"],
            cooked_weight_g=total_weight,
            aliases=[name],
        )

    _clear_state(context)
    await query.edit_message_text(
        f"✅ *{name}* сохранено в базу!\n\n"
        f"На 100 г: *{food.kcal:.0f} ккал* | "
        f"Б {food.protein_g:.1f} / Ж {food.fat_g:.1f} / У {food.carbs_g:.1f} г\n\n"
        f"_Теперь пиши «150 г {name}» — запишу сразу._",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def handle_calc_skip_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    _clear_state(context)
    await query.edit_message_text("✅ Готово. Блюдо не сохранено в базу.")
    return ConversationHandler.END


# ─── Cancel ───────────────────────────────────────────────────────────────────


async def handle_calc_cancel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    _clear_state(context)
    try:
        await query.edit_message_text("✖️ Отменено.")
    except Exception:
        pass
    return ConversationHandler.END


async def handle_calc_cancel_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    _clear_state(context)
    if update.effective_message is not None:
        await update.effective_message.reply_text("✖️ Расчёт отменён.")
    return ConversationHandler.END


# ─── Wiring ───────────────────────────────────────────────────────────────────


def build_calculate_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("calculate", handle_calculate_command)],
        states={
            _Step.COLLECTING: [
                CallbackQueryHandler(handle_calc_done_callback, pattern=r"^calc:done$"),
                CallbackQueryHandler(
                    handle_calc_cancel_callback, pattern=r"^calc:cancel$"
                ),
                CommandHandler("cancel", handle_calc_cancel_command),
                # TEXT & ~COMMAND catches both direct messages and forwarded messages
                # (forward_origin is set but the message is still TEXT type).
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_calc_ingredient_message
                ),
            ],
            _Step.NAMING: [
                CallbackQueryHandler(handle_calc_save_callback, pattern=r"^calc:save$"),
                CallbackQueryHandler(handle_calc_skip_callback, pattern=r"^calc:skip$"),
                CallbackQueryHandler(
                    handle_calc_cancel_callback, pattern=r"^calc:cancel$"
                ),
                CommandHandler("cancel", handle_calc_cancel_command),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_calc_name_message
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handle_calc_cancel_command),
            CallbackQueryHandler(
                handle_calc_cancel_callback, pattern=r"^calc:cancel$"
            ),
        ],
        name="dish_calculator",
        persistent=True,
        per_chat=True,
        per_user=True,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _sum_macros(items: list[MealItemPayload]) -> dict:
    return {
        "kcal": sum(it.kcal for it in items),
        "protein_g": sum(it.protein_g for it in items),
        "fat_g": sum(it.fat_g for it in items),
        "carbs_g": sum(it.carbs_g for it in items),
    }


def _render_panel(items: list[MealItemPayload]) -> str:
    if not items:
        return (
            "🧮 *Калькулятор блюда*\n\n"
            "Отправляй ингредиенты с весом — одним или несколькими сообщениями. "
            "Можно переслать список из другого чата.\n\n"
            "Пример:\n"
            "`куриная грудка 800`\n"
            "`картошка 1739`\n"
            "`морковь 495`\n\n"
            "Когда добавишь всё — нажми *✅ Готово*."
        )

    lines = ["🧮 *Ингредиенты:*"]
    for it in items:
        lines.append(
            f"• {it.food_name} — {it.amount:g} {it.unit} ({it.kcal:.0f} ккал)"
        )
    totals = _sum_macros(items)
    total_weight = sum(it.weight_g for it in items)
    lines.append("")
    lines.append(
        f"⚖️ {total_weight:.0f} г · "
        f"🔥 {totals['kcal']:.0f} ккал | "
        f"Б {totals['protein_g']:.0f} / Ж {totals['fat_g']:.0f} / У {totals['carbs_g']:.0f} г"
    )
    lines.append("")
    lines.append("Добавляй ещё или нажми *✅ Готово*.")
    return "\n".join(lines)


async def _refresh_panel(
    context: ContextTypes.DEFAULT_TYPE, items: list[MealItemPayload]
) -> None:
    panel_msg_id = context.user_data.get(_KEY_PANEL_MSG_ID)
    panel_chat_id = context.user_data.get(_KEY_PANEL_CHAT_ID)
    if not panel_msg_id or not panel_chat_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=panel_chat_id,
            message_id=panel_msg_id,
            text=_render_panel(items),
            parse_mode="Markdown",
            reply_markup=_DONE_KEYBOARD,
        )
    except Exception:
        logger.debug("Panel refresh failed", exc_info=True)


def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (_KEY_ITEMS, _KEY_NAME, _KEY_PANEL_MSG_ID, _KEY_PANEL_CHAT_ID):
        context.user_data.pop(key, None)
