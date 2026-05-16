from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from app.repositories.user_repo import upsert_user_from_telegram
from app.core.config import settings
from app.db.session import async_session_factory


WELCOME = (
    "👋 Привет, {name}!\n\n"
    "Я NutriSnap — твой дневник питания.\n"
    "Отправь мне:\n"
    "  📸 фото тарелки\n"
    "  🎙 голосовое сообщение\n"
    "  ✏️ описание текстом\n\n"
    "...и я сам посчитаю КБЖУ и запишу приём пищи.\n\n"
    "Чтобы рассчитать твою суточную норму — нажми /onboard."
)


async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    async with async_session_factory() as session:
        user = await upsert_user_from_telegram(session, update.effective_user)

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
    rows.append([InlineKeyboardButton("⚙️ Расчёт нормы (/onboard)", callback_data="onboard")])
    keyboard = InlineKeyboardMarkup(rows)

    await update.effective_message.reply_text(
        WELCOME.format(name=user.first_name or "друг"),
        reply_markup=keyboard,
    )
