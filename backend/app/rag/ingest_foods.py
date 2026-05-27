"""Embed every Food row from Postgres into the Qdrant `foods` collection.

Run:
    podman compose -f docker-compose.dev.yml exec api python -m app.rag.ingest_foods

Idempotent: Qdrant `upsert` uses `point.id == str(food.id)`, so re-running
overwrites embeddings/payloads without duplication. Safe to run after every
`seed_foods` invocation, and from a CI step that warms the catalog on deploy.
"""

from __future__ import annotations

import asyncio
import logging

from qdrant_client.models import PointStruct
from sqlalchemy import select

from app.db.models import Food
from app.db.session import async_session_factory
from app.rag.embeddings import embed_texts
from app.rag.qdrant import (
    build_food_embedding_text,
    build_food_payload,
    ensure_foods_collection,
    upsert_food_points,
)

logger = logging.getLogger(__name__)

# OpenAI embeddings endpoint accepts up to 2048 inputs per call; we cap lower
# to keep individual responses small and retries cheap.
_BATCH_SIZE = 256


async def ingest_all_foods() -> int:
    """Re-embed every Food in PG and upsert into Qdrant. Returns count."""
    await ensure_foods_collection()
    async with async_session_factory() as session:
        foods = list((await session.scalars(select(Food))).all())

    if not foods:
        logger.warning("No Food rows in PG — nothing to ingest")
        return 0

    total = 0
    for batch_start in range(0, len(foods), _BATCH_SIZE):
        batch = foods[batch_start : batch_start + _BATCH_SIZE]
        texts = [build_food_embedding_text(f) for f in batch]
        vectors = await embed_texts(texts)
        points = [
            PointStruct(
                id=str(food.id),
                vector=vec,
                payload=build_food_payload(food),
            )
            for food, vec in zip(batch, vectors, strict=True)
        ]
        await upsert_food_points(points)
        total += len(points)
        logger.info(
            "Upserted batch %d/%d (running total: %d)",
            batch_start // _BATCH_SIZE + 1,
            (len(foods) + _BATCH_SIZE - 1) // _BATCH_SIZE,
            total,
        )

    return total


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    count = await ingest_all_foods()
    print(f"✅ Ingested {count} foods into Qdrant")


if __name__ == "__main__":
    asyncio.run(main())
