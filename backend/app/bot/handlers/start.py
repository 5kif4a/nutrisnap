from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.handlers.onboard import _Step
from app.core.config import settings
from app.db.session import async_session_factory
from app.repositories.user_repo import upsert_user_from_telegram


WELCOME_RETURNING = (
    "👋 С возвращением, {name}!\n\n"
    "Отправь мне:\n"
    "  📸 фото тарелки\n"
    "  🎙 голосовое сообщение\n"
    "  ✏️ описание текстом\n\n"
    "...и я посчитаю КБЖУ и запишу приём пищи."
)

WELCOME_FIRST_TIME = (
    "👋 Привет, {name}!\n\n"
    "Я NutriSnap — твой дневник питания. Я умею считать КБЖУ по фото / голосу / тексту.\n\n"
    "Прежде чем начнём — давай рассчитаем твою суточную норму. Это займёт минуту.\n\n"
    "Твой пол?"
)


async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry-point of the onboarding ConversationHandler.

    First-time users (no profile yet) drop straight into the sex question.
    Returning users get a normal welcome and the conversation ends immediately.
    """
    if update.effective_user is None or update.effective_message is None:
        return ConversationHandler.END

    async with async_session_factory() as session:
        user = await upsert_user_from_telegram(session, update.effective_user)

    name = user.first_name or "друг"

    if not user.is_onboarded:
        sex_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("👨 Мужской", callback_data="onboard_sex:male"),
                    InlineKeyboardButton("👩 Женский", callback_data="onboard_sex:female"),
                ]
            ]
        )
        await update.effective_message.reply_text(
            WELCOME_FIRST_TIME.format(name=name),
            reply_markup=sex_keyboard,
        )
        return _Step.SEX

    rows: list[list[InlineKeyboardButton]] = []
    # Telegram requires https for Web App buttons — skip in local http dev.
    if settings.MINI_APP_URL.startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    "📊 Открыть дневник",
                    web_app=WebAppInfo(url=settings.MINI_APP_URL),
                )
            ]
        )
    rows.append([InlineKeyboardButton("⚙️ Пересчитать норму", callback_data="onboard")])
    keyboard = InlineKeyboardMarkup(rows)

    await update.effective_message.reply_text(
        WELCOME_RETURNING.format(name=name),
        reply_markup=keyboard,
    )
    return ConversationHandler.END
