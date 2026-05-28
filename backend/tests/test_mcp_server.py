"""Unit tests for the Nutrition MCP server tools and their core logic.

No DB / network: the source-resolution chain's dependencies are monkeypatched
and the compute tool is pure. Covers tool registration, the local-catalog
resolution chain, the LLM-estimate refusal policy (branded + Atwater
plausibility), and portion math.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.models import FoodMetric, FoodSource
from app.mcp import server as srv
from app.services.openai_client import NutritionEstimate


def _fake_food(**kw):
    """Lightweight stand-in for a Food row (resolve_food returns rows as-is)."""
    defaults = dict(
        id=None,
        name="x",
        metric=FoodMetric.GRAMS,
        kcal=100.0,
        protein_g=1.0,
        fat_g=1.0,
        carbs_g=1.0,
        piece_weight_g=None,
        source=FoodSource.CURATED,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _fake_estimate(**kw) -> NutritionEstimate:
    defaults = dict(
        name="плов",
        metric=FoodMetric.GRAMS,
        kcal=250,
        protein_g=10,
        fat_g=5,
        carbs_g=40,
    )
    defaults.update(kw)
    return NutritionEstimate(**defaults)


async def test_registers_expected_tools():
    tools = await srv.mcp.list_tools()
    assert sorted(t.name for t in tools) == [
        "compute_meal_item_nutrition",
        "estimate_food_nutrition",
        "lookup_food",
        "resolve_meal_item",
    ]


# ─── compute_portion_nutrition (pure) ────────────────────────────────────────


def test_compute_grams_scales_per_100g():
    res = srv.compute_portion_nutrition(
        metric=FoodMetric.GRAMS,
        kcal=165,
        protein_g=31,
        fat_g=3.6,
        carbs_g=0,
        piece_weight_g=None,
        amount=200,
        unit=FoodMetric.GRAMS,
    )
    assert res.ok
    assert res.weight_g == 200
    assert res.kcal == pytest.approx(330)
    assert res.protein_g == pytest.approx(62)


def test_compute_cross_converts_grams_to_pieces():
    # egg: 70 kcal/piece, 50 g/piece; user logs 200 g → 4 pieces → 280 kcal
    res = srv.compute_portion_nutrition(
        metric=FoodMetric.PIECE,
        kcal=70,
        protein_g=6,
        fat_g=5,
        carbs_g=0.5,
        piece_weight_g=50,
        amount=200,
        unit=FoodMetric.GRAMS,
    )
    assert res.ok
    assert res.kcal == pytest.approx(280)
    assert res.weight_g == pytest.approx(200)


def test_compute_returns_error_for_incompatible_unit():
    # weight-based food, no piece weight, user says "2 pieces" → not computable
    res = srv.compute_portion_nutrition(
        metric=FoodMetric.GRAMS,
        kcal=100,
        protein_g=1,
        fat_g=1,
        carbs_g=1,
        piece_weight_g=None,
        amount=2,
        unit=FoodMetric.PIECE,
    )
    assert res.ok is False
    assert res.error


# ─── is_nutrition_plausible (pure Atwater check) ─────────────────────────────


def test_plausibility_accepts_realistic_macros():
    # chicken breast: 165 kcal, 31P, 3.6F, 0C → derived 4·31 + 9·3.6 = 156.4 → ratio 0.95
    assert srv.is_nutrition_plausible(
        _fake_estimate(kcal=165, protein_g=31, fat_g=3.6, carbs_g=0)
    )


def test_plausibility_rejects_zero_kcal():
    assert not srv.is_nutrition_plausible(
        _fake_estimate(kcal=0, protein_g=10, fat_g=5, carbs_g=40)
    )


def test_plausibility_rejects_implausible_ratio():
    # whey-style hallucination: 12 kcal claimed but macros say ~360 — 30× off
    assert not srv.is_nutrition_plausible(
        _fake_estimate(kcal=12, protein_g=80, fat_g=2, carbs_g=8)
    )


# ─── resolve_food source-priority chain ──────────────────────────────────────


def _stub_chain(monkeypatch, **overrides):
    """Default to 'everything empty' and override individual steps per test."""

    async def none_bc(_s, _bc):
        return None

    async def empty_local(_s, _n, limit=1):
        return []

    monkeypatch.setattr(
        srv, "lookup_food_by_barcode", overrides.get("lookup_food_by_barcode", none_bc)
    )
    monkeypatch.setattr(
        srv, "search_foods_by_name", overrides.get("search_foods_by_name", empty_local)
    )


async def test_resolve_food_local_barcode_short_circuits(monkeypatch):
    local = _fake_food(name="local")

    async def fake_barcode(_session, _bc):
        return local

    async def fail(*_a, **_k):
        raise AssertionError("later source should not run")

    _stub_chain(
        monkeypatch,
        lookup_food_by_barcode=fake_barcode,
        search_foods_by_name=fail,
    )

    out = await srv.resolve_food(object(), "milk", "123")
    assert out is local


async def test_resolve_food_falls_through_to_name_then_none(monkeypatch):
    """No barcode hit and no name hit → None (caller falls back to LLM estimate)."""
    _stub_chain(monkeypatch)
    out = await srv.resolve_food(object(), "редкий продукт", None)
    assert out is None


async def test_resolve_food_strict_is_currently_a_noop(monkeypatch):
    """`strict` is reserved for future external-source gating; today it must
    not break the local-catalog path."""
    local = _fake_food(name="local")

    async def name_hit(_s, _n, limit=1):
        return [local]

    _stub_chain(monkeypatch, search_foods_by_name=name_hit)
    out = await srv.resolve_food(object(), "milk", None, brand="X", strict=True)
    assert out is local


# ─── estimate_food_nutrition tool ─────────────────────────────────────────────


async def test_estimate_tool_returns_ephemeral_result(monkeypatch):
    async def fake_estimate(name):
        return _fake_estimate(name=name)

    monkeypatch.setattr(srv, "estimate_nutrition", fake_estimate)

    res = await srv.estimate_food_nutrition("плов")
    assert res.found is True
    assert res.food_id is None  # ephemeral — never persisted
    assert res.source is FoodSource.LLM_ESTIMATE
    assert res.kcal == 250


async def test_estimate_tool_refuses_branded_items(monkeypatch):
    async def fail_estimate(_name):
        raise AssertionError("estimate must NOT be called for branded items")

    monkeypatch.setattr(srv, "estimate_nutrition", fail_estimate)

    res = await srv.estimate_food_nutrition("Ultra Whey", brand="Maxler")
    assert res.found is False
    assert "branded" in (res.reason or "").lower()


async def test_estimate_tool_rejects_implausible_macros(monkeypatch):
    # 12 kcal but 80g protein → ratio ~30 → must be rejected
    async def fake_estimate(_name):
        return _fake_estimate(kcal=12, protein_g=80, fat_g=2, carbs_g=8)

    monkeypatch.setattr(srv, "estimate_nutrition", fake_estimate)

    res = await srv.estimate_food_nutrition("странная еда")
    assert res.found is False
    assert "implausible" in (res.reason or "")


