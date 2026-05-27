from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    ENV: Literal["development", "production"] = "development"

    # Telegram
    BOT_TOKEN: str
    MINI_APP_URL: str = "http://localhost:5173"
    WEBHOOK_SECRET: str = "dev-secret-change-me"
    WEBHOOK_BASE_URL: str | None = (
        None  # public URL of the API (Railway) — needed to register webhook
    )

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://nutrisnap:nutrisnap@localhost:5432/nutrisnap"
    )

    # OpenAI
    OPENAI_API_KEY: str
    VISION_MODEL: str = "gpt-4o"
    TEXT_MODEL: str = "gpt-4o-mini"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "foods"

    # LangSmith
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_API_KEY: str | None = None
    LANGCHAIN_PROJECT: str = "nutrisnap"

    # FatSecret (optional fallback). Basic tier requires IP whitelist — point
    # FATSECRET_PROXY_URL at a static-IP proxy (e.g. Fixie / QuotaGuard) whose
    # outbound IP is whitelisted in the FatSecret developer console. Without
    # the proxy, requests from Railway's rotating IPs will be rejected.
    FATSECRET_CLIENT_ID: str | None = None
    FATSECRET_CLIENT_SECRET: str | None = None
    FATSECRET_PROXY_URL: str | None = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def force_asyncpg_scheme(cls, value: str) -> str:
        # Railway gives `postgresql://...` — SQLAlchemy async needs `postgresql+asyncpg://`
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


settings = Settings()
