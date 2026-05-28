"""Run the bot in polling mode for local development.

Webhooks require a public URL — for local dev we just poll.
Usage:
    uv run python -m app.bot.run_polling
"""

import logging

from telegram.ext import Application, ApplicationBuilder

from app.bot.application import _build_persistence, register_handlers
from app.core.config import settings
from app.mcp.client import start_nutrition_mcp, stop_nutrition_mcp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


async def _on_post_init(_app: Application) -> None:
    """Spawn the Nutrition MCP server before the first update is handled.

    Polling mode doesn't run the FastAPI lifespan, so the MCP startup that
    lives in `app.main.lifespan` never fires here — we hook it via PTB's
    post_init instead. Without this the nutrition_lookup node raises
    'MCP tool lookup_food not loaded' on the first food message.
    """
    await start_nutrition_mcp()


async def _on_post_shutdown(_app: Application) -> None:
    await stop_nutrition_mcp()


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(settings.BOT_TOKEN)
        .persistence(_build_persistence())
        .post_init(_on_post_init)
        .post_shutdown(_on_post_shutdown)
        .build()
    )
    register_handlers(app)
    logging.info("Bot starting in polling mode...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
