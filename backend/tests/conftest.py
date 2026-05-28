"""Test bootstrap — provide dummy env for required settings before app imports.

`app.core.config.Settings` has required fields (BOT_TOKEN, OPENAI_API_KEY) and is
instantiated at import time. conftest is imported before any test module, so
setting these here lets the app package import without real secrets. No test in
this suite touches the network or a real database.
"""

import os

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENV", "development")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
