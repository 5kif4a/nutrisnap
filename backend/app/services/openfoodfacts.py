"""Open Food Facts integration — barcode lookup + text search.

Public, no API key, no IP whitelist. Free and multilingual (lang=ru).
"""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from app.db.models import FoodMetric, FoodSource
from app.repositories.food_repo import ExternalFoodPayload

logger = logging.getLogger(__name__)

_BASE_URL = "https://world.openfoodfacts.org"
_USER_AGENT = "NutriSnap/0.1 (nFactorial final project; contact: @nutrisnap_bot)"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@lru_cache(maxsize=1)
def get_off_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_BASE_URL,
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    )


# ─── Public callables ────────────────────────────────────────────────────────


async def lookup_food_by_barcode(barcode: str) -> ExternalFoodPayload | None:
    """Lookup a product by EAN/UPC barcode via OFF v2 API."""
    client = get_off_client()
    try:
        resp = await client.get(f"/api/v2/product/{barcode}.json")
    except httpx.HTTPError as exc:
        logger.warning("OFF barcode lookup failed for %s: %s", barcode, exc)
        return None

    if resp.status_code != 200:
        return None

    data = resp.json()
    if data.get("status") != 1:
        return None  # not found

    return _map_off_product(data["product"], barcode=barcode)


async def search_foods_by_text(
    query: str, *, limit: int = 5
) -> list[ExternalFoodPayload]:
    """Text search via OFF's search endpoint. Returns ExternalFoodPayload list."""
    client = get_off_client()
    try:
        resp = await client.get(
            "/cgi/search.pl",
            params={
                "search_terms": query,
                "search_simple": 1,
                "action": "process",
                "json": 1,
                "page_size": limit,
                "lc": "ru",
            },
        )
    except httpx.HTTPError as exc:
        logger.warning("OFF text search failed for %r: %s", query, exc)
        return []

    if resp.status_code != 200:
        return []

    products = resp.json().get("products", [])
    payloads: list[ExternalFoodPayload] = []
    for product in products:
        mapped = _map_off_product(product, barcode=product.get("code"))
        if mapped is not None:
            payloads.append(mapped)
    return payloads


# ─── Internal mapping ────────────────────────────────────────────────────────


def _map_off_product(
    product: dict, *, barcode: str | None
) -> ExternalFoodPayload | None:
    """Convert OFF product dict → our ExternalFoodPayload.

    Returns None if nutrition values are missing — OFF has lots of incomplete entries.
    """
    nutriments = product.get("nutriments", {}) or {}

    kcal = _pick_first_float(
        nutriments,
        ("energy-kcal_100g", "energy-kcal_value"),
    )
    protein = _pick_first_float(nutriments, ("proteins_100g",))
    fat = _pick_first_float(nutriments, ("fat_100g",))
    carbs = _pick_first_float(nutriments, ("carbohydrates_100g",))

    if kcal is None or protein is None or fat is None or carbs is None:
        return None
    # Reject incomplete entries — OFF has many products with zero kcal which is
    # almost always missing data (real foods have at least a few kcal/100g).
    if kcal <= 0:
        return None

    name = (
        product.get("product_name_ru")
        or product.get("product_name")
        or product.get("generic_name_ru")
        or product.get("generic_name")
    )
    if not name:
        return None

    # OFF stores everything per 100g (default) or per 100ml depending on product.
    # The `nutrition_data_per` field signals which; default to "100g".
    per = (product.get("nutrition_data_per") or "100g").lower()
    metric = FoodMetric.MILLILITERS if per == "100ml" else FoodMetric.GRAMS

    brand_field = product.get("brands") or None
    brand = brand_field.split(",")[0].strip() if brand_field else None

    aliases: list[str] = []
    if product.get("product_name") and product.get("product_name") != name:
        aliases.append(product["product_name"])
    if product.get("generic_name_ru") and product.get("generic_name_ru") != name:
        aliases.append(product["generic_name_ru"])

    return ExternalFoodPayload(
        name=name.strip()[:255],
        metric=metric,
        kcal=kcal,
        protein_g=protein,
        fat_g=fat,
        carbs_g=carbs,
        source=FoodSource.OPEN_FOOD_FACTS,
        brand=brand,
        barcode=barcode,
        aliases=aliases or None,
        external_id=product.get("code") or barcode,
    )


def _pick_first_float(d: dict, keys: tuple[str, ...]) -> float | None:
    for k in keys:
        value = d.get(k)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
