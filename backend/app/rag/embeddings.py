"""OpenAI embeddings — `text-embedding-3-small`, 1536-dim.

Used by both the foods catalog ingest and the recommender's query path.
Kept separate from `services/openai_client.py` so the embeddings client is
not coupled to the LLM client (different rate-limits, different SDK
methods, simpler reasoning about latency).
"""

from __future__ import annotations

from functools import lru_cache

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI

from app.core.config import settings

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


@lru_cache(maxsize=1)
def get_openai_embeddings_client() -> AsyncOpenAI:
    # wrap_openai → embeddings calls show up as LLM-typed runs with usage
    # metadata, so LangSmith prices them in the cost column.
    return wrap_openai(AsyncOpenAI(api_key=settings.OPENAI_API_KEY))


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed a list of texts. Returns vectors in the same order as input."""
    if not texts:
        return []
    client = get_openai_embeddings_client()
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def embed_text(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
