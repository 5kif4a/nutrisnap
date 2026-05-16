import logging

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot.handlers.common import (
    handle_help_command,
    handle_open_command,
    handle_today_command,
    handle_week_command,
)
from app.bot.handlers.meal import (
    handle_cancel_meal_callback,
    handle_photo_message,
    handle_save_meal_callback,
    handle_text_message,
    handle_voice_message,
)
from app.bot.handlers.onboard import build_onboarding_handler
from app.bot.handlers.start import handle_start_command
from app.core.config import settings

logger = logging.getLogger(__name__)


def build_telegram_application() -> Application:
    """Construct PTB Application with all handlers registered. Webhook-ready."""
    application = (
        ApplicationBuilder()
        .token(settings.BOT_TOKEN)
        .updater(None)  # webhook mode — no Updater polling
        .build()
    )

    application.add_handler(CommandHandler("start", handle_start_command))
    application.add_handler(CommandHandler("help", handle_help_command))
    application.add_handler(CommandHandler("open", handle_open_command))
    application.add_handler(CommandHandler("today", handle_today_command))
    application.add_handler(CommandHandler("week", handle_week_command))

    # Onboarding conversation — must be registered BEFORE the generic text handler,
    # otherwise the weight/height/age inputs will be eaten by the meal parser.
    application.add_handler(build_onboarding_handler())

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    application.add_handler(CallbackQueryHandler(handle_save_meal_callback, pattern=r"^save:"))
    application.add_handler(CallbackQueryHandler(handle_cancel_meal_callback, pattern=r"^cancel:"))

    logger.info("Telegram application built — %d handlers", len(application.handlers[0]))
    return application


async def process_telegram_update(application: Application, payload: dict) -> None:
    """Feed a single webhook payload into the Application's update queue."""
    update = Update.de_json(payload, application.bot)
    if update is None:
        return
    await application.process_update(update)
