"""Run the bot in polling mode for local development.

Webhooks require a public URL — for local dev we just poll.
Usage:
    uv run python -m app.bot.run_polling
"""

import logging

from telegram.ext import ApplicationBuilder

from app.bot.application import register_handlers
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def main() -> None:
    app = ApplicationBuilder().token(settings.BOT_TOKEN).build()
    register_handlers(app)
    logging.info("Bot starting in polling mode...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
