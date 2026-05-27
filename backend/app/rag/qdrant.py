"""Qdrant client singleton + collection bootstrap + semantic search helpers."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

from app.core.config import settings
from app.db.models import Food
from app.rag.embeddings import EMBEDDING_DIM, embed_text

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_qdrant_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=settings.QDRANT_URL)


async def ensure_foods_collection() -> None:
    """Create the `foods` collection if it doesn't exist yet."""
    client = get_qdrant_client()
    existing = await client.get_collections()
    names = {c.name for c in existing.collections}
    if settings.QDRANT_COLLECTION in names:
        return
    await client.create_collection(
        collection_name=settings.QDRANT_COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )
    logger.info("Created Qdrant collection %s", settings.QDRANT_COLLECTION)


async def upsert_food_points(points: list[PointStruct]) -> None:
    """Batch upsert points into the foods collection."""
    if not points:
        return
    client = get_qdrant_client()
    await client.upsert(
        collection_name=settings.QDRANT_COLLECTION,
        points=points,
    )


def build_food_embedding_text(food: Food) -> str:
    """Compose embedding input for a single Food.

    Mirrors `ingest_foods._build_embedding_text` so on-demand embeds use the
    same representation as the batch ingest.
    """
    parts = [food.name]
    if food.brand:
        parts.append(food.brand)
    if food.cuisine:
        parts.append(food.cuisine)
    if food.aliases:
        parts.extend(food.aliases[:5])
    return " · ".join(parts)


def build_food_payload(food: Food) -> dict:
    return {
        "food_id": str(food.id),
        "name": food.name,
        "brand": food.brand,
        "metric": str(food.metric),
        "kcal": food.kcal,
        "protein_g": food.protein_g,
        "fat_g": food.fat_g,
        "carbs_g": food.carbs_g,
        "piece_weight_g": food.piece_weight_g,
        "source": str(food.source),
    }


async def index_food_in_qdrant(food: Food) -> None:
    """Embed one Food and upsert it into the Qdrant catalog.

    Called as a fire-and-forget task whenever a new Food row is persisted
    (OFF cache hit, user recipe save) so the catalog vector index stays in
    sync with PG without a manual `ingest_foods` rerun.
    """
    try:
        await ensure_foods_collection()
        text = build_food_embedding_text(food)
        vector = await embed_text(text)
        await upsert_food_points(
            [
                PointStruct(
                    id=str(food.id),
                    vector=vector,
                    payload=build_food_payload(food),
                )
            ]
        )
    except Exception:
        # Indexing is an enhancement, not a correctness boundary — never let
        # an embedding/Qdrant outage break the bot's main reply.
        logger.exception("Failed to index food %s in Qdrant", food.id)


def schedule_food_indexing(food: Food) -> None:
    """Fire-and-forget Qdrant index for a freshly persisted Food row."""
    asyncio.create_task(index_food_in_qdrant(food))


async def search_foods_semantic(
    query: str,
    *,
    limit: int = 5,
    source_filter: list[str] | None = None,
    exclude_food_ids: list[str] | None = None,
    min_protein_per_100: float | None = None,
) -> list[dict]:
    """Semantic search over the foods catalog.

    `source_filter` — restrict to specific FoodSource values (e.g. ["curated",
    "user_recipe"] to avoid OFF noise).
    `exclude_food_ids` — drop these from the result (useful for "show me
    something I haven't tried recently").
    `min_protein_per_100` — light macro filter for protein-focused recs.
    """
    client = get_qdrant_client()
    vec = await embed_text(query)

    must: list[FieldCondition] = []
    must_not: list[FieldCondition] = []
    if source_filter:
        must.append(FieldCondition(key="source", match=MatchAny(any=source_filter)))
    if min_protein_per_100 is not None:
        must.append(
            FieldCondition(key="protein_g", range=Range(gte=min_protein_per_100))
        )
    if exclude_food_ids:
        for fid in exclude_food_ids:
            must_not.append(FieldCondition(key="food_id", match=MatchValue(value=fid)))

    qfilter = Filter(must=must, must_not=must_not) if (must or must_not) else None

    # qdrant-client 1.18+: `.search` was deprecated in favour of `.query_points`.
    response = await client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=vec,
        limit=limit,
        query_filter=qfilter,
    )
    return [{"score": p.score, **(p.payload or {})} for p in response.points]
