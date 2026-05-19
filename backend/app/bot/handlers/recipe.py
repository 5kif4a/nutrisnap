"""Recipe builder ConversationHandler.

State machine (per user):

    [entry: 🍳 button under photo result] ──► COLLECTING
        ├── photo  → run vision, append ingredients, update panel
        ├── ✅ done → AWAIT_TOTAL_WEIGHT
        └── ✖️ cancel → END (draft discarded)

    AWAIT_TOTAL_WEIGHT
        └── text (number) → save Food row → AWAIT_PORTION

    AWAIT_PORTION
        └── text (number) → log Meal → END

See docs/BOT_FEATURES.md (Recipe builder) for the rationale.
"""

from __future__ import annotations

import io
import logging
from enum import IntEnum

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.bot.keyboards import (
    build_recipe_cancel_keyboard,
    build_recipe_collecting_keyboard,
    build_recipe_post_save_keyboard,
)
from app.db.models import FoodMetric, InputSource, MealType
from app.db.session import async_session_factory
from app.graph.graph import get_meal_graph
from app.repositories.food_repo import save_user_recipe
from app.repositories.meal_repo import MealItemPayload, log_meal_with_items
from app.repositories.user_repo import get_user_by_tg_id
from app.services.meal_drafts import pop_draft
from app.services.meal_type_inference import infer_meal_type_by_clock
from app.services.recipe_drafts import (
    RecipeDraft,
    append_ingredients,
    get_draft,
    pop_draft as pop_recipe_draft,
    put_draft,
    update_draft,
)

logger = logging.getLogger(__name__)


class _Step(IntEnum):
    COLLECTING = 10
    AWAIT_TOTAL_WEIGHT = 11
    # After the recipe is saved we ask the user whether to also log a portion
    # right now or stop here. Distinct state so a stray number doesn't get
    # interpreted as a portion before they choose.
    AWAIT_POST_SAVE_CHOICE = 12
    AWAIT_PORTION = 13


# ─── Entry from the photo-result keyboard ────────────────────────────────────

async def handle_recipe_start_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User tapped 🍳 under the photo result — seed a recipe draft."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()

    try:
        _, _, meal_draft_id = query.data.split(":", 2)
    except ValueError:
        await query.edit_message_text("⚠️ Неверный callback")
        return ConversationHandler.END

    meal_draft = await pop_draft(meal_draft_id)
    if meal_draft is None:
        await query.edit_message_text("⏱ Черновик уже не действителен — пришли фото ещё раз.")
        return ConversationHandler.END

    # The recipe name comes from the original caption when available;
    # otherwise we ask the user later by editing the panel.
    name = (meal_draft.raw_input or "").strip() or "Мой рецепт"
    draft = RecipeDraft(
        user_telegram_id=update.effective_user.id,
        chat_id=query.message.chat_id if query.message else 0,
        name=name,
        ingredients=list(meal_draft.items),
    )
    await put_draft(draft)

    panel_text = _render_collecting_panel(draft)
    await query.edit_message_text(panel_text, reply_markup=build_recipe_collecting_keyboard())
    if query.message is not None:
        await update_draft(
            update.effective_user.id, panel_message_id=query.message.message_id
        )
    return _Step.COLLECTING


# ─── COLLECTING state ────────────────────────────────────────────────────────

async def handle_recipe_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User sends one more ingredient photo while collecting."""
    if update.effective_message is None or update.effective_user is None:
        return _Step.COLLECTING
    msg = update.effective_message
    if not msg.photo:
        return _Step.COLLECTING

    draft = await get_draft(update.effective_user.id)
    if draft is None:
        await msg.reply_text("⏱ Рецепт-сессия уже не активна. Пришли фото и начни заново.")
        return ConversationHandler.END

    # Note: albums in recipe mode are processed one photo at a time. The
    # user can also send single photos for forgotten ingredients.
    photo_bytes = await _download_largest_photo(msg)
    caption = msg.caption or ""

    pinging = await msg.reply_text("🔍 Добавляю ингредиент...")
    state = {
        "raw_input_type": "photo",
        "photo_bytes_list": [photo_bytes],
        "caption": caption,
        "telegram_user_id": update.effective_user.id,
        "tg_message_id": update.update_id,
    }
    try:
        graph = get_meal_graph()
        result = await graph.ainvoke(state)
    except Exception as exc:
        logger.exception("Recipe-photo graph invocation failed")
        await pinging.edit_text(f"⚠️ Не смог обработать фото: {exc.__class__.__name__}")
        return _Step.COLLECTING

    resolved = result.get("resolved_items") or []
    if not resolved:
        await pinging.edit_text("Не разглядел ингредиент 🤔 Попробуй с другого ракурса.")
        return _Step.COLLECTING

    new_items: list[MealItemPayload] = [r["payload"] for r in resolved]
    draft = await append_ingredients(update.effective_user.id, new_items)
    if draft is None:
        await pinging.edit_text("⏱ Рецепт-сессия истекла.")
        return ConversationHandler.END

    await pinging.edit_text(
        "Добавил:\n"
        + "\n".join(f"• {it.food_name} — {it.amount:g} {it.unit.value}" for it in new_items)
    )
    await _refresh_panel(context, draft)
    return _Step.COLLECTING


async def handle_recipe_done_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return _Step.COLLECTING
    await query.answer()

    draft = await get_draft(update.effective_user.id)
    if draft is None or not draft.ingredients:
        if query.message is not None:
            await query.edit_message_text("⏱ Рецепт-сессия пуста или истекла.")
        return ConversationHandler.END

    # Lock the panel — no more ingredients.
    panel_text = _render_collecting_panel(draft) + "\n\n⚖️ Жду общий вес готового блюда…"
    await query.edit_message_text(panel_text, reply_markup=None)

    await query.message.reply_text(
        "⚖️ Сколько весит готовое блюдо в граммах?\n\n"
        "Взвесь блюдо в посуде → вычти вес посуды → напиши число.\n"
        "Пример: <code>320</code>",
        parse_mode="HTML",
        reply_markup=build_recipe_cancel_keyboard(),
    )
    return _Step.AWAIT_TOTAL_WEIGHT


# ─── AWAIT_TOTAL_WEIGHT state ────────────────────────────────────────────────

async def handle_recipe_total_weight(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None or update.effective_user is None:
        return _Step.AWAIT_TOTAL_WEIGHT
    text = update.effective_message.text or ""
    weight = _parse_positive_float(text)
    if weight is None or not 20 <= weight <= 10_000:
        await update.effective_message.reply_text(
            "Не похоже на вес. Напиши число от 20 до 10000 (граммов готового блюда)."
        )
        return _Step.AWAIT_TOTAL_WEIGHT

    draft = await get_draft(update.effective_user.id)
    if draft is None or not draft.ingredients:
        await update.effective_message.reply_text("⏱ Рецепт-сессия истекла.")
        return ConversationHandler.END

    totals = _sum_macros(draft.ingredients)
    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, update.effective_user.id)
        if user is None:
            await update.effective_message.reply_text("⚠️ Сначала /start")
            return ConversationHandler.END
        food = await save_user_recipe(
            session,
            user=user,
            name=draft.name,
            ingredients_total_kcal=totals["kcal"],
            ingredients_total_protein_g=totals["protein_g"],
            ingredients_total_fat_g=totals["fat_g"],
            ingredients_total_carbs_g=totals["carbs_g"],
            cooked_weight_g=weight,
            aliases=[draft.name],
        )
    await update_draft(
        update.effective_user.id,
        cooked_weight_g=weight,
        saved_food_id=str(food.id),
    )

    per_100 = (
        f"🍽 *{draft.name}* — рецепт сохранён ✅\n\n"
        f"На 100 г готового блюда:\n"
        f"🔥 {food.kcal:.0f} ккал | Б {food.protein_g:.1f} / Ж {food.fat_g:.1f} / У {food.carbs_g:.1f}\n\n"
        f"_В следующий раз достаточно написать «150 г {draft.name}» — сразу запишу._\n\n"
        f"Что дальше?"
    )
    await update.effective_message.reply_text(
        per_100,
        parse_mode="Markdown",
        reply_markup=build_recipe_post_save_keyboard(),
    )
    return _Step.AWAIT_POST_SAVE_CHOICE


# ─── AWAIT_POST_SAVE_CHOICE state ────────────────────────────────────────────

async def handle_recipe_log_portion_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User chose to also log a portion as today's meal."""
    query = update.callback_query
    if query is None or update.effective_user is None:
        return _Step.AWAIT_POST_SAVE_CHOICE
    await query.answer()

    draft = await get_draft(update.effective_user.id)
    if draft is None or draft.cooked_weight_g is None:
        if query.message is not None:
            await query.edit_message_text("⏱ Рецепт-сессия истекла.")
        return ConversationHandler.END

    if query.message is not None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "⚖️ Сколько ты съел? Напиши вес порции в граммах.\n\n"
            "Пример: <code>150</code>",
            parse_mode="HTML",
            reply_markup=build_recipe_cancel_keyboard(),
        )
    return _Step.AWAIT_PORTION


async def handle_recipe_done_no_meal_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User chose to keep the recipe but not log any portion right now."""
    query = update.callback_query
    if query is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()

    draft = await pop_recipe_draft(update.effective_user.id)
    context.user_data.pop("recipe_portion_item", None)
    name = draft.name if draft else "рецепт"
    if query.message is not None:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            f"✅ Готово. Рецепт *«{name}»* теперь в твоём каталоге.\n\n"
            f"Когда поешь — просто напиши «N г {name}» или пришли фото, "
            f"и я сразу запишу в дневник без пересчёта.",
            parse_mode="Markdown",
        )
    return ConversationHandler.END


# ─── AWAIT_PORTION state ─────────────────────────────────────────────────────

async def handle_recipe_portion(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None or update.effective_user is None:
        return _Step.AWAIT_PORTION
    text = update.effective_message.text or ""
    portion = _parse_positive_float(text)
    if portion is None or not 1 <= portion <= 5_000:
        await update.effective_message.reply_text(
            "Не похоже на порцию. Напиши число от 1 до 5000 г."
        )
        return _Step.AWAIT_PORTION

    draft = await pop_recipe_draft(update.effective_user.id)
    if draft is None or draft.cooked_weight_g is None or not draft.ingredients:
        await update.effective_message.reply_text("⏱ Рецепт-сессия истекла.")
        return ConversationHandler.END

    # Scale stored totals (raw ingredients = cooked dish) to the actual portion.
    totals = _sum_macros(draft.ingredients)
    factor = portion / draft.cooked_weight_g
    portion_item = MealItemPayload(
        food_name=draft.name,
        amount=portion,
        unit=FoodMetric.GRAMS,
        weight_g=portion,
        kcal=totals["kcal"] * factor,
        protein_g=totals["protein_g"] * factor,
        fat_g=totals["fat_g"] * factor,
        carbs_g=totals["carbs_g"] * factor,
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🍳 Завтрак", callback_data="recipe_meal:breakfast"),
                InlineKeyboardButton("🥗 Обед", callback_data="recipe_meal:lunch"),
            ],
            [
                InlineKeyboardButton("🍽 Ужин", callback_data="recipe_meal:dinner"),
                InlineKeyboardButton("🍪 Перекус", callback_data="recipe_meal:snack"),
            ],
        ]
    )
    context.user_data["recipe_portion_item"] = portion_item
    await update.effective_message.reply_text(
        f"📋 Порция: *{draft.name}* — {portion:g} г\n"
        f"🔥 {portion_item.kcal:.0f} ккал | "
        f"Б {portion_item.protein_g:.1f} / Ж {portion_item.fat_g:.1f} / У {portion_item.carbs_g:.1f}\n\n"
        "Куда записать?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return _Step.AWAIT_PORTION  # stays here until meal-type is picked


async def handle_recipe_meal_type_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User picked breakfast/lunch/dinner/snack for the recipe portion."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()
    try:
        meal_type = MealType(query.data.split(":", 1)[1])
    except (ValueError, KeyError):
        await query.edit_message_text("⚠️ Неверный тип приёма")
        return ConversationHandler.END

    item: MealItemPayload | None = context.user_data.pop("recipe_portion_item", None)
    if item is None:
        await query.edit_message_text("⏱ Порция уже не действительна.")
        return ConversationHandler.END

    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, update.effective_user.id)
        if user is None:
            await query.edit_message_text("⚠️ Сначала /start")
            return ConversationHandler.END
        await log_meal_with_items(
            session,
            user=user,
            meal_type=meal_type,
            items=[item],
            source=InputSource.PHOTO,
            raw_input=item.food_name,
        )

    label = {
        MealType.BREAKFAST: "завтрак",
        MealType.LUNCH: "обед",
        MealType.DINNER: "ужин",
        MealType.SNACK: "перекус",
    }[meal_type]
    await query.edit_message_text(
        f"✅ Записано в {label}! +{item.kcal:.0f} ккал\n\n"
        f"_Рецепт «{item.food_name}» сохранён — в следующий раз просто напиши «150 г {item.food_name}»._",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─── Cancel ──────────────────────────────────────────────────────────────────

async def handle_recipe_cancel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()
    await pop_recipe_draft(update.effective_user.id)
    context.user_data.pop("recipe_portion_item", None)
    try:
        await query.edit_message_text("✖️ Рецепт отменён.")
    except Exception:
        pass
    return ConversationHandler.END


# ─── Wiring ──────────────────────────────────────────────────────────────────

def build_recipe_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_recipe_start_callback, pattern=r"^recipe:start:"),
        ],
        states={
            _Step.COLLECTING: [
                MessageHandler(filters.PHOTO, handle_recipe_photo),
                CallbackQueryHandler(handle_recipe_done_callback, pattern=r"^recipe:done$"),
                CallbackQueryHandler(handle_recipe_cancel_callback, pattern=r"^recipe:cancel$"),
            ],
            _Step.AWAIT_TOTAL_WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_recipe_total_weight),
                CallbackQueryHandler(handle_recipe_cancel_callback, pattern=r"^recipe:cancel$"),
            ],
            _Step.AWAIT_POST_SAVE_CHOICE: [
                CallbackQueryHandler(handle_recipe_log_portion_callback, pattern=r"^recipe:log_portion$"),
                CallbackQueryHandler(handle_recipe_done_no_meal_callback, pattern=r"^recipe:done_no_meal$"),
                CallbackQueryHandler(handle_recipe_cancel_callback, pattern=r"^recipe:cancel$"),
            ],
            _Step.AWAIT_PORTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_recipe_portion),
                CallbackQueryHandler(handle_recipe_meal_type_callback, pattern=r"^recipe_meal:"),
                CallbackQueryHandler(handle_recipe_cancel_callback, pattern=r"^recipe:cancel$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(handle_recipe_cancel_callback, pattern=r"^recipe:cancel$")],
        name="recipe_builder",
        persistent=False,
        per_chat=True,
        per_user=True,
    )


# ─── Internals ───────────────────────────────────────────────────────────────

async def _download_largest_photo(msg) -> bytes:
    photo = msg.photo[-1]
    photo_file = await photo.get_file()
    buf = io.BytesIO()
    await photo_file.download_to_memory(out=buf)
    return buf.getvalue()


def _sum_macros(items: list[MealItemPayload]) -> dict:
    return {
        "kcal": sum(it.kcal for it in items),
        "protein_g": sum(it.protein_g for it in items),
        "fat_g": sum(it.fat_g for it in items),
        "carbs_g": sum(it.carbs_g for it in items),
    }


def _render_collecting_panel(draft: RecipeDraft) -> str:
    lines = [f"🍳 *Рецепт: {draft.name}*", "", "Ингредиенты:"]
    for it in draft.ingredients:
        lines.append(f"• {it.food_name} — {it.amount:g} {it.unit.value} ({it.kcal:.0f} ккал)")
    totals = _sum_macros(draft.ingredients)
    lines.append("")
    lines.append(
        f"Итого сырых: {totals['kcal']:.0f} ккал | "
        f"Б {totals['protein_g']:.0f} / Ж {totals['fat_g']:.0f} / У {totals['carbs_g']:.0f}"
    )
    lines.append("")
    lines.append("Добавляй ещё фото ингредиентов или нажми *✅ Готово*, когда всё взвесил.")
    return "\n".join(lines)


async def _refresh_panel(context: ContextTypes.DEFAULT_TYPE, draft: RecipeDraft) -> None:
    if draft.panel_message_id is None:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=draft.chat_id,
            message_id=draft.panel_message_id,
            text=_render_collecting_panel(draft),
            parse_mode="Markdown",
            reply_markup=build_recipe_collecting_keyboard(),
        )
    except Exception:
        logger.debug("Recipe panel refresh failed", exc_info=True)


def _parse_positive_float(text: str) -> float | None:
    try:
        v = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return v if v > 0 else None
