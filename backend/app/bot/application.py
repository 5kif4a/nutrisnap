import logging

from telegram import Update
from pathlib import Path

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PicklePersistence,
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
    handle_quick_add_callback,
    handle_save_meal_callback,
    handle_text_message,
    handle_voice_message,
)
from app.bot.handlers.onboard import build_onboarding_handler
from app.bot.handlers.recipe import build_recipe_handler
from app.bot.handlers.recommend import (
    handle_recommend_add_callback,
    handle_recommend_command,
)
from app.bot.jobs import register_jobs
from app.core.config import settings

logger = logging.getLogger(__name__)


def register_handlers(application: Application) -> None:
    """Single source of truth for handler registration.

    Used by both `build_telegram_application` (webhook mode, prod) and
    `app.bot.run_polling.main` (polling mode, local dev). Keep these flows in
    sync — registration order matters (ConversationHandler before generic text).
    """
    # Onboarding conversation owns /start so first-time users are forced through
    # the RSK flow. Must be registered BEFORE the generic text handler, otherwise
    # the weight/height/age inputs would be eaten by the meal parser.
    application.add_handler(build_onboarding_handler())

    # Recipe builder — owns the `recipe:start:<draft_id>` callback. While active
    # it also intercepts photos and text messages, so it must be registered
    # BEFORE the generic photo/text handlers.
    application.add_handler(build_recipe_handler())

    application.add_handler(CommandHandler("help", handle_help_command))
    application.add_handler(CommandHandler("open", handle_open_command))
    application.add_handler(CommandHandler("today", handle_today_command))
    application.add_handler(CommandHandler("week", handle_week_command))
    application.add_handler(CommandHandler("recommend", handle_recommend_command))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    application.add_handler(
        CallbackQueryHandler(handle_save_meal_callback, pattern=r"^save:")
    )
    application.add_handler(
        CallbackQueryHandler(handle_quick_add_callback, pattern=r"^qadd:")
    )
    application.add_handler(
        CallbackQueryHandler(handle_recommend_add_callback, pattern=r"^radd:")
    )
    application.add_handler(
        CallbackQueryHandler(handle_cancel_meal_callback, pattern=r"^cancel:")
    )

    # Scheduled jobs — daily morning nudge etc.
    register_jobs(application)


def _build_persistence() -> PicklePersistence:
    """Pickle-file persistence for ConversationHandler state.

    Without this every container restart wipes mid-onboarding conversations —
    users would tap a sex/activity button whose callback became orphaned.
    Path lives under /tmp in dev (volume mount picks it up in compose); in
    prod Railway should mount a small disk so it survives deploys.
    """
    path = Path("/tmp/ptb_state.pickle")
    return PicklePersistence(filepath=path)


def build_telegram_application() -> Application:
    """Construct PTB Application with all handlers registered. Webhook-ready."""
    application = (
        ApplicationBuilder()
        .token(settings.BOT_TOKEN)
        .updater(None)  # webhook mode — no Updater polling
        .persistence(_build_persistence())
        .build()
    )
    register_handlers(application)
    logger.info(
        "Telegram application built — %d handlers", len(application.handlers[0])
    )
    return application


async def process_telegram_update(application: Application, payload: dict) -> None:
    """Feed a single webhook payload into the Application's update queue."""
    update = Update.de_json(payload, application.bot)
    if update is None:
        return
    await application.process_update(update)
