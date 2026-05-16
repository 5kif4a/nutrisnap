"""Run the bot in polling mode for local development.

Webhooks require a public URL — for local dev we just poll.
Usage:
    uv run python -m app.bot.run_polling
"""

import logging

from telegram.ext import (
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def main() -> None:
    app = ApplicationBuilder().token(settings.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start_command))
    app.add_handler(CommandHandler("help", handle_help_command))
    app.add_handler(CommandHandler("open", handle_open_command))
    app.add_handler(CommandHandler("today", handle_today_command))
    app.add_handler(CommandHandler("week", handle_week_command))

    # Onboarding conversation — register BEFORE the generic text handler.
    app.add_handler(build_onboarding_handler())

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    app.add_handler(CallbackQueryHandler(handle_save_meal_callback, pattern=r"^save:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_meal_callback, pattern=r"^cancel:"))

    logging.info("Bot starting in polling mode...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
