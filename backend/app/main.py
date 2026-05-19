import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.bot.application import build_telegram_application, process_telegram_update
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("nutrisnap")


@asynccontextmanager
async def lifespan(app: FastAPI):
    telegram_app = build_telegram_application()
    app.state.telegram_app = telegram_app

    await telegram_app.initialize()
    await telegram_app.start()

    if settings.WEBHOOK_BASE_URL:
        webhook_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/telegram/webhook"
        await telegram_app.bot.set_webhook(
            url=webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logger.info("Telegram webhook registered at %s", webhook_url)
    else:
        logger.warning(
            "WEBHOOK_BASE_URL not set — webhook NOT registered. "
            "Set it to the public API URL in prod (e.g. https://...railway.app)."
        )

    try:
        yield
    finally:
        if settings.WEBHOOK_BASE_URL:
            await telegram_app.bot.delete_webhook()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="NutriSnap API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.MINI_APP_URL,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    # Allow Vercel preview/prod deployments without re-configuring per URL.
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def get_health_status() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def handle_telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid secret")

    payload = await request.json()
    telegram_app = request.app.state.telegram_app
    await process_telegram_update(telegram_app, payload)
    return {"ok": True}
