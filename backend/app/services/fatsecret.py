"""FatSecret Platform API — fallback nutrition source.

Falls under our OFF tier in the lookup chain: covers western/brand foods that
OFF misses (and rare EN-only entries). OAuth 2.0 client_credentials with a
24h token; we cache the token in-process and refresh ~60s before expiry.

Whitelist constraint
--------------------
FatSecret's Basic tier requires the *outbound IP* to be whitelisted in the
developer console. Railway hands out rotating IPs, so prod traffic must egress
through a static-IP proxy (Fixie / QuotaGuard / Railway static IP add-on).
Set `FATSECRET_PROXY_URL` to that proxy and httpx routes every call through it.

If client_id / client_secret are not configured, every public call returns
an empty list — i.e. the chain transparently skips FatSecret.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache

import httpx

from app.core.config import settings
from app.db.models import FoodMetric, FoodSource
from app.repositories.food_repo import ExternalFoodPayload

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
_API_URL = "https://platform.fatsecret.com/rest/server.api"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_TOKEN_REFRESH_SKEW_S = 60  # refresh slightly before expiry to avoid races

# Module-level OAuth token cache (mutable, refreshed in `_ensure_token`).
# pylint treats module-level names as constants and complains about lowercase;
# but these are mutable singletons by design, not constants.
_token_value: str | None = None  # pylint: disable=invalid-name
_token_expires_at: float = 0.0  # pylint: disable=invalid-name
_token_lock = asyncio.Lock()


def is_fatsecret_configured() -> bool:
    return bool(settings.FATSECRET_CLIENT_ID and settings.FATSECRET_CLIENT_SECRET)


@lru_cache(maxsize=1)
def get_fatsecret_client() -> httpx.AsyncClient:
    kwargs: dict = {"timeout": _TIMEOUT}
    if settings.FATSECRET_PROXY_URL:
        kwargs["proxy"] = settings.FATSECRET_PROXY_URL
    return httpx.AsyncClient(**kwargs)


# ─── Public callables ────────────────────────────────────────────────────────


async def search_foods_by_text(
    query: str, *, limit: int = 5
) -> list[ExternalFoodPayload]:
    """Text search via `foods.search.v3`. Returns ExternalFoodPayload list."""
    if not is_fatsecret_configured():
        return []

    token = await _get_access_token()
    if token is None:
        return []

    client = get_fatsecret_client()
    try:
        resp = await client.get(
            _API_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "method": "foods.search.v3",
                "search_expression": query,
                "max_results": limit,
                "include_food_images": "false",
                "format": "json",
            },
        )
    except httpx.HTTPError as exc:
        logger.warning("FatSecret text search failed for %r: %s", query, exc)
        return []

    if resp.status_code != 200:
        logger.warning(
            "FatSecret text search returned %s for %r: %s",
            resp.status_code,
            query,
            resp.text[:300],
        )
        return []

    data = resp.json()
    # FatSecret returns HTTP 200 even on API-level errors — body is then
    # `{"error": {"code": N, "message": "..."}}`. Most common in our setup:
    # code 21 ("Invalid IP address detected") when the egress IP isn't on
    # FatSecret's whitelist. Surface it so it doesn't look like a miss.
    if "error" in data:
        logger.warning("FatSecret API error for %r: %s", query, data["error"])
        return []
    # v3 returns `foods_search.results.food` (list). Empty searches return
    # `{"foods_search": {"max_results": "...", "total_results": "0", ...}}`.
    results = (data.get("foods_search") or {}).get("results") or {}
    foods = results.get("food") or []
    if isinstance(foods, dict):  # single-result FatSecret quirk
        foods = [foods]

    payloads: list[ExternalFoodPayload] = []
    for food in foods:
        mapped = _map_fatsecret_food(food)
        if mapped is not None:
            payloads.append(mapped)
    return payloads


# ─── Token management ───────────────────────────────────────────────────────


async def _get_access_token() -> str | None:
    """Return a valid bearer token, fetching/refreshing on demand."""
    global _token_value, _token_expires_at  # pylint: disable=global-statement

    if _token_value is not None and time.time() < _token_expires_at:
        return _token_value

    async with _token_lock:
        # Re-check inside the lock: another coroutine may have refreshed it.
        if _token_value is not None and time.time() < _token_expires_at:
            return _token_value

        client = get_fatsecret_client()
        try:
            resp = await client.post(
                _TOKEN_URL,
                auth=(
                    settings.FATSECRET_CLIENT_ID or "",
                    settings.FATSECRET_CLIENT_SECRET or "",
                ),
                data={"grant_type": "client_credentials", "scope": "basic"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            logger.warning("FatSecret token request failed: %s", exc)
            return None

        if resp.status_code != 200:
            logger.warning(
                "FatSecret token request returned %s: %s",
                resp.status_code,
                resp.text[:300],
            )
            return None

        body = resp.json()
        access_token = body.get("access_token")
        expires_in = int(body.get("expires_in", 0))
        if not access_token or expires_in <= 0:
            logger.warning("FatSecret token response malformed: %s", body)
            return None

        _token_value = access_token
        _token_expires_at = time.time() + expires_in - _TOKEN_REFRESH_SKEW_S
        return _token_value


# ─── Internal mapping ────────────────────────────────────────────────────────


def _map_fatsecret_food(food: dict) -> ExternalFoodPayload | None:
    """Convert FatSecret `food` dict → ExternalFoodPayload normalized per 100g/ml.

    Picks a per-100-unit metric serving when available; otherwise rescales any
    metric serving with a positive amount. Returns None if no usable serving.
    """
    name = food.get("food_name")
    if not name:
        return None

    servings_obj = food.get("servings") or {}
    raw_servings = servings_obj.get("serving") or []
    if isinstance(raw_servings, dict):  # single-serving FatSecret quirk
        raw_servings = [raw_servings]
    if not raw_servings:
        return None

    metric_servings = [s for s in raw_servings if _has_metric_amount(s)]
    if not metric_servings:
        return None

    # Prefer servings whose metric amount is exactly 100 (then already per-100).
    # Otherwise take the first metric serving and rescale.
    serving = next(
        (
            s
            for s in metric_servings
            if abs(float(s["metric_serving_amount"]) - 100.0) < 0.01
        ),
        metric_servings[0],
    )

    metric_unit = (serving.get("metric_serving_unit") or "g").lower()
    metric_amount = float(serving["metric_serving_amount"])
    factor = 100.0 / metric_amount if metric_amount > 0 else 1.0

    try:
        kcal = float(serving.get("calories", 0)) * factor
        protein = float(serving.get("protein", 0)) * factor
        fat = float(serving.get("fat", 0)) * factor
        carbs = float(serving.get("carbohydrate", 0)) * factor
    except (TypeError, ValueError):
        return None

    if kcal <= 0:
        return None  # almost always missing-data; same heuristic as OFF mapping

    food_metric = FoodMetric.MILLILITERS if metric_unit == "ml" else FoodMetric.GRAMS

    brand = food.get("brand_name") or None
    food_id = food.get("food_id")

    return ExternalFoodPayload(
        name=name.strip()[:255],
        metric=food_metric,
        kcal=kcal,
        protein_g=protein,
        fat_g=fat,
        carbs_g=carbs,
        source=FoodSource.FATSECRET,
        brand=brand,
        external_id=str(food_id) if food_id is not None else None,
    )


def _has_metric_amount(serving: dict) -> bool:
    """True iff the serving carries a positive metric_serving_amount in g or ml."""
    unit = (serving.get("metric_serving_unit") or "").lower()
    amount_raw = serving.get("metric_serving_amount")
    if unit not in {"g", "ml"} or amount_raw is None:
        return False
    try:
        return float(amount_raw) > 0
    except (TypeError, ValueError):
        return False
