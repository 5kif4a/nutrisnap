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


_DISAMBIG_MIN_SCORE = 0.50
_DISAMBIG_MAX_SPREAD = 0.20  # top-1 minus top-2 must be ≤ this to flag ambiguity


async def fetch_disambiguation_candidates(
    query: str, *, limit: int = 3
) -> list[dict]:
    """Return top Qdrant hits if they're close enough to be ambiguous.

    Returns an empty list when there's a single clear winner (score gap > 0.20)
    or when fewer than 2 candidates meet the minimum score threshold.
    Each dict is the raw Qdrant payload with an added "score" key.
    """
    results = await search_foods_semantic(query, limit=limit + 1)
    scored = [r for r in results if r.get("score", 0) >= _DISAMBIG_MIN_SCORE]
    if len(scored) < 2:
        return []
    if scored[0]["score"] - scored[1]["score"] > _DISAMBIG_MAX_SPREAD:
        return []

    # Deduplicate by lowercased name so "Сникерс" and "сникерс" don't both appear.
    seen: set[str] = set()
    unique: list[dict] = []
    for r in scored[:limit]:
        key = (r.get("name") or "").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    return unique if len(unique) >= 2 else []


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
