"""/onboard — ConversationHandler that builds the user's daily nutrition targets.

Flow:
    /start any time → /onboard
        → ask SEX        (inline keyboard)
        → ask WEIGHT     (text, kg)
        → ask HEIGHT     (text, cm)
        → ask AGE        (text, years)
        → ask ACTIVITY   (inline keyboard, 5 levels)
        → ask GOAL       (inline keyboard, lose / maintain / gain)
        → compute TDEE + macros, persist, show summary.

Saves via `save_user_profile`, which uses `compute_daily_targets` (Mifflin-St Jeor).
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.bot.handlers.onboard_state import OnboardStep as _Step
from app.bot.handlers.start import handle_start_command
from app.core.config import settings
from app.db.models import ActivityLevel, Goal, Sex
from app.db.session import async_session_factory
from app.repositories.user_repo import (
    get_user_by_tg_id,
    save_user_profile,
    upsert_user_from_telegram,
)


_ACTIVITY_LABELS: dict[ActivityLevel, str] = {
    ActivityLevel.SEDENTARY: "🪑 Сидячий (мало движения)",
    ActivityLevel.LIGHT: "🚶 Лёгкая (1-3 тренировки/нед)",
    ActivityLevel.MODERATE: "🏃 Умеренная (3-5 тренировок/нед)",
    ActivityLevel.ACTIVE: "🏋️ Высокая (6-7 тренировок/нед)",
    ActivityLevel.VERY_ACTIVE: "🔥 Очень высокая (физ. труд)",
}

_GOAL_LABELS: dict[Goal, str] = {
    Goal.LOSE: "📉 Похудеть",
    Goal.MAINTAIN: "⚖️ Поддерживать вес",
    Goal.GAIN: "📈 Набрать массу",
}

_SEX_LABELS: dict[Sex, str] = {
    Sex.MALE: "👨 Мужской",
    Sex.FEMALE: "👩 Женский",
}


async def _mark_answered(update: Update, choice_label: str) -> None:
    """Append the user's pick to the prompt and strip the keyboard.

    Keeps the onboarding flow visible as chat history instead of overwriting
    every step into a single edited bubble.
    """
    query = update.callback_query
    if query is None or query.message is None:
        return
    original = query.message.text or ""
    try:
        await query.edit_message_text(f"{original}\n\n→ {choice_label}")
    except Exception:
        # If the message can't be edited (too old, etc.), at least drop the keyboard.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


# ─── Entry points ────────────────────────────────────────────────────────────


async def start_onboarding_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_user is None or update.effective_message is None:
        return ConversationHandler.END

    async with async_session_factory() as session:
        await upsert_user_from_telegram(session, update.effective_user)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👨 Мужской", callback_data="onboard_sex:male"),
                InlineKeyboardButton("👩 Женский", callback_data="onboard_sex:female"),
            ]
        ]
    )
    await update.effective_message.reply_text(
        "Давай рассчитаем твою суточную норму КБЖУ.\n\nТвой пол?",
        reply_markup=keyboard,
    )
    return _Step.SEX


async def start_onboarding_from_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Callback for the 'Расчёт нормы' button on /start welcome message."""
    if update.callback_query is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    return await start_onboarding_command(update, context)


# ─── State handlers ──────────────────────────────────────────────────────────


async def handle_sex_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return _Step.SEX
    await query.answer()
    sex = Sex(query.data.split(":", 1)[1])
    context.user_data["onboard_sex"] = sex

    await _mark_answered(update, _SEX_LABELS[sex])
    await query.message.reply_text(
        "⚖️ Сколько ты весишь? Напиши число в кг (например 72)"
    )
    return _Step.WEIGHT


async def handle_weight_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return _Step.WEIGHT
    weight = _parse_positive_float(update.effective_message.text)
    if weight is None or not 30 <= weight <= 300:
        await update.effective_message.reply_text(
            "Не похоже на вес 🤔 Напиши число от 30 до 300 кг (например 72)"
        )
        return _Step.WEIGHT
    context.user_data["onboard_weight"] = weight
    await update.effective_message.reply_text(
        "📏 Какой у тебя рост? Напиши в см (например 178)"
    )
    return _Step.HEIGHT


async def handle_height_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return _Step.HEIGHT
    height = _parse_positive_float(update.effective_message.text)
    if height is None or not 100 <= height <= 250:
        await update.effective_message.reply_text(
            "Не похоже на рост. Напиши число от 100 до 250 см"
        )
        return _Step.HEIGHT
    context.user_data["onboard_height"] = height
    await update.effective_message.reply_text("🎂 Сколько тебе лет?")
    return _Step.AGE


async def handle_age_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return _Step.AGE
    age = _parse_positive_int(update.effective_message.text)
    if age is None or not 10 <= age <= 120:
        await update.effective_message.reply_text(
            "Не похоже на возраст. Напиши число от 10 до 120"
        )
        return _Step.AGE
    context.user_data["onboard_age"] = age

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label, callback_data=f"onboard_activity:{level.value}"
                )
            ]
            for level, label in _ACTIVITY_LABELS.items()
        ]
    )
    await update.effective_message.reply_text(
        "🏃 Какой у тебя уровень активности?", reply_markup=keyboard
    )
    return _Step.ACTIVITY


async def handle_activity_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return _Step.ACTIVITY
    await query.answer()
    activity = ActivityLevel(query.data.split(":", 1)[1])
    context.user_data["onboard_activity"] = activity

    await _mark_answered(update, _ACTIVITY_LABELS[activity])
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"onboard_goal:{goal.value}")]
            for goal, label in _GOAL_LABELS.items()
        ]
    )
    await query.message.reply_text("🎯 Какая у тебя цель?", reply_markup=keyboard)
    return _Step.GOAL


async def handle_goal_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return _Step.GOAL
    await query.answer()
    goal = Goal(query.data.split(":", 1)[1])

    await _mark_answered(update, _GOAL_LABELS[goal])
    context.user_data["onboard_goal"] = goal

    # LOSE / GAIN → ask for target weight before finalizing. MAINTAIN falls
    # through and persists immediately.
    if goal is not Goal.MAINTAIN:
        current_weight = context.user_data.get("onboard_weight")
        prompt = (
            f"🎯 Какой у тебя целевой вес в кг?\n\nСейчас: {current_weight:g} кг"
            if current_weight
            else "🎯 Какой у тебя целевой вес в кг?"
        )
        await query.message.reply_text(prompt)
        return _Step.TARGET_WEIGHT

    return await _finalize_onboarding(update, context, target_weight_kg=None)


async def handle_target_weight_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return _Step.TARGET_WEIGHT
    target = _parse_positive_float(update.effective_message.text)
    if target is None or not 30 <= target <= 300:
        await update.effective_message.reply_text(
            "Не похоже на вес. Напиши число от 30 до 300 кг."
        )
        return _Step.TARGET_WEIGHT

    current = context.user_data.get("onboard_weight")
    goal: Goal = context.user_data.get("onboard_goal", Goal.MAINTAIN)
    if current is not None:
        if goal is Goal.LOSE and target >= current:
            await update.effective_message.reply_text(
                f"Целевой вес должен быть меньше текущего ({current:g} кг) для цели «похудеть». "
                "Напиши число меньше."
            )
            return _Step.TARGET_WEIGHT
        if goal is Goal.GAIN and target <= current:
            await update.effective_message.reply_text(
                f"Целевой вес должен быть больше текущего ({current:g} кг) для цели «набрать массу». "
                "Напиши число больше."
            )
            return _Step.TARGET_WEIGHT

    return await _finalize_onboarding(update, context, target_weight_kg=target)


async def _finalize_onboarding(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    target_weight_kg: float | None,
) -> int:
    """Persist the collected profile + send the summary message."""
    if update.effective_user is None:
        return ConversationHandler.END

    sex: Sex = context.user_data.pop("onboard_sex")
    weight: float = context.user_data.pop("onboard_weight")
    height: float = context.user_data.pop("onboard_height")
    age: int = context.user_data.pop("onboard_age")
    activity: ActivityLevel = context.user_data.pop("onboard_activity")
    goal: Goal = context.user_data.pop("onboard_goal")

    chat = update.effective_chat
    chat_id = chat.id if chat is not None else None

    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, update.effective_user.id)
        if user is None:
            if chat_id is not None:
                await context.bot.send_message(chat_id, "⚠️ Сначала /start")
            return ConversationHandler.END
        user = await save_user_profile(
            session,
            user,
            sex=sex,
            weight_kg=weight,
            height_cm=height,
            age=age,
            activity=activity,
            goal=goal,
            target_weight_kg=target_weight_kg,
        )

    target_line = ""
    if user.target_weight_kg is not None and user.weight_kg is not None:
        delta = user.target_weight_kg - user.weight_kg
        arrow = "↓" if delta < 0 else "↑"
        target_line = (
            f"🎯 *Цель*: {user.weight_kg:g} кг → {user.target_weight_kg:g} кг "
            f"({arrow}{abs(delta):g} кг)\n\n"
        )

    summary = (
        "✅ Готово! Твоя суточная норма:\n\n"
        + target_line
        + f"🔥 *Калории*: {user.tdee_kcal} ккал\n"
        f"🥩 *Белки*: {user.target_protein_g} г\n"
        f"🥑 *Жиры*: {user.target_fat_g} г\n"
        f"🍞 *Углеводы*: {user.target_carbs_g} г\n\n"
        "Теперь записывай еду — фото, голос, текст или форвард.\n\n"
        "⚙️ Параметры профиля (вес, цель, активность) и нормы можно "
        "поменять в любой момент в Mini App."
    )
    reply_markup: InlineKeyboardMarkup | None = None
    if settings.MINI_APP_URL.startswith("https://"):
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📊 Открыть Mini App",
                        web_app=WebAppInfo(url=settings.MINI_APP_URL),
                    )
                ]
            ]
        )

    if chat_id is not None:
        await context.bot.send_message(
            chat_id=chat_id,
            text=summary,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    return ConversationHandler.END


async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Отменил расчёт. Можно повторить через /onboard"
        )
    for k in (
        "onboard_sex",
        "onboard_weight",
        "onboard_height",
        "onboard_age",
        "onboard_activity",
        "onboard_goal",
    ):
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ─── Wiring ──────────────────────────────────────────────────────────────────


def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", handle_start_command),
            CommandHandler("onboard", start_onboarding_command),
            CallbackQueryHandler(start_onboarding_from_button, pattern=r"^onboard$"),
        ],
        states={
            _Step.SEX: [
                CallbackQueryHandler(handle_sex_selection, pattern=r"^onboard_sex:"),
            ],
            _Step.WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_input),
            ],
            _Step.HEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_height_input),
            ],
            _Step.AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_age_input),
            ],
            _Step.ACTIVITY: [
                CallbackQueryHandler(
                    handle_activity_selection, pattern=r"^onboard_activity:"
                ),
            ],
            _Step.GOAL: [
                CallbackQueryHandler(handle_goal_selection, pattern=r"^onboard_goal:"),
            ],
            _Step.TARGET_WEIGHT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_target_weight_input
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_onboarding)],
        name="onboarding",
        persistent=True,
    )


# ─── Internals ───────────────────────────────────────────────────────────────


def _parse_positive_float(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_positive_int(text: str) -> int | None:
    try:
        value = int(text.strip())
    except ValueError:
        return None
    return value if value > 0 else None
