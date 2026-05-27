from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from app.core.config import settings


HELP_TEXT = (
    "🥦 NutriSnap — команды:\n\n"
    "/start — приветствие и регистрация\n"
    "/onboard — расчёт суточной нормы КБЖУ\n"
    "/today — сводка за сегодня\n"
    "/week — сводка за неделю\n"
    "/open — открыть Mini App\n"
    "/help — это сообщение\n\n"
    "Или просто пришли мне фото, голосовое или текст с едой."
)


async def handle_help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(HELP_TEXT)


async def handle_open_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message is None:
        return
    if not settings.MINI_APP_URL.startswith("https://"):
        await update.effective_message.reply_text(
            "ℹ️ Mini App ещё не задеплоен — в dev он работает только по https. "
            "Запусти фронт на каком-нибудь tunneling (ngrok / cloudflared) и обнови MINI_APP_URL."
        )
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📊 Открыть дневник",
                    web_app=WebAppInfo(url=settings.MINI_APP_URL),
                )
            ]
        ]
    )
    await update.effective_message.reply_text(
        "Открой Mini App для подробной статистики 📈",
        reply_markup=keyboard,
    )


async def handle_today_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message is None:
        return
    # TODO: реальная сводка из БД через get_daily_summary MCP tool
    await update.effective_message.reply_text(
        "📅 Сводка за сегодня будет здесь (скоро)"
    )


async def handle_week_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message is None:
        return
    # TODO: weekly summary
    await update.effective_message.reply_text("📊 Сводка за неделю будет здесь (скоро)")
