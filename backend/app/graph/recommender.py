"""LangGraph subgraph for `/recommend` — RAG-based meal recommendations.

Pipeline (4 thin nodes, see docs/ARCHITECTURE_VARIANTS.md — Variant B):

    START
      │
      ▼
    gather_user_state   (PG: today totals + targets + frequent foods)
      │
      ▼
    compute_deficit     (pure Python: which macro is most short?)
      │
      ▼
    retrieve_candidates (Qdrant: semantic search filtered by deficit + variety)
      │
      ▼
    compose_recommendation (gpt-4o-mini: pick 3 with rationale)
      │
      ▼
     END

Designed to be invoked from three triggers (Phase 4):
  • /recommend command
  • daily morning nudge
  • post-meal hook (when meal was big or day is ending)
The `intent` field on the state distinguishes them so prompts/filters tune
to context (e.g. variety-mode for nudge after monotonous days).
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import distinct, select

from app.db.models import Meal, MealItem, MealType, User
from app.db.session import async_session_factory
from app.repositories.food_repo import list_frequent_foods_per_meal_type
from app.repositories.meal_repo import fetch_daily_summary
from app.repositories.user_repo import get_user_by_tg_id
from app.rag.qdrant import search_foods_semantic
from app.services.openai_client import get_openai_client
from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── State ────────────────────────────────────────────────────────────────────

RecommendIntent = Literal["deficit", "variety", "freeform"]
DeficitMacro = Literal["protein", "fat", "carbs", "kcal"] | None


class CandidateFood(TypedDict, total=False):
    food_id: str
    name: str
    brand: str | None
    metric: str
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    piece_weight_g: float | None
    source: str
    score: float


class RecommendedItem(BaseModel):
    food_id: str = Field(description="Qdrant point id (Food.id UUID)")
    name: str
    brand: str | None = None
    suggested_grams: float = Field(gt=0, description="Recommended portion in grams")
    kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    rationale_short: str = Field(
        description="One short Russian sentence: why this fits the user now"
    )


class RecommendationResult(BaseModel):
    items: list[RecommendedItem]
    summary: str = Field(description="2-3 sentence Russian summary of the day so far")


class RecommendState(TypedDict, total=False):
    # ── Input ──────────────────────────────────────────────────────────────
    telegram_user_id: int
    intent: RecommendIntent
    freeform_query: str  # only when intent="freeform"

    # ── Intermediate ───────────────────────────────────────────────────────
    user_id: str
    today_totals: dict  # {kcal, protein_g, fat_g, carbs_g, meals_count}
    targets: dict  # {kcal, protein_g, fat_g, carbs_g}
    favorite_food_names: list[str]
    recent_food_ids: list[str]  # to exclude for variety (14d window)
    deficit_macro: DeficitMacro
    deficit_grams: float  # how much more of `deficit_macro` user needs
    candidates: list[CandidateFood]

    # ── Output ─────────────────────────────────────────────────────────────
    recommendations: list[RecommendedItem]
    summary: str
    error: str


# ─── Nodes ────────────────────────────────────────────────────────────────────


async def gather_user_state_node(state: RecommendState) -> RecommendState:
    """Pull today's totals, targets, and the user's recent eating patterns."""
    today = date_cls.today()
    async with async_session_factory() as session:
        user = await get_user_by_tg_id(session, state["telegram_user_id"])
        if user is None:
            state["error"] = "user not onboarded"
            return state

        state["user_id"] = str(user.id)
        summary = await fetch_daily_summary(session, user, today)
        state["today_totals"] = {
            "kcal": summary.total_kcal,
            "protein_g": summary.total_protein_g,
            "fat_g": summary.total_fat_g,
            "carbs_g": summary.total_carbs_g,
            "meals_count": summary.meals_count,
        }
        state["targets"] = {
            "kcal": summary.target_kcal or 2000,
            "protein_g": summary.target_protein_g or 100,
            "fat_g": summary.target_fat_g or 70,
            "carbs_g": summary.target_carbs_g or 250,
        }
        state["favorite_food_names"] = await _fetch_favorite_food_names(session, user)
        state["recent_food_ids"] = await _fetch_recent_food_ids(session, user)
    return state


async def _fetch_favorite_food_names(session, user: User) -> list[str]:
    """Top frequent foods across ALL meal types in the last 30 days — used as
    semantic anchors for 'similar to what user likes' retrieval."""
    seen: set[str] = set()
    names: list[str] = []
    for mt in MealType:
        rows = await list_frequent_foods_per_meal_type(session, user, mt, limit=3)
        for r in rows:
            key = r.food_name.lower()
            if key not in seen:
                seen.add(key)
                names.append(r.food_name)
    return names[:6]


async def _fetch_recent_food_ids(session, user: User, days: int = 14) -> list[str]:
    """food_ids the user logged in the last `days` days (variety filter)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(distinct(MealItem.food_id))
        .select_from(MealItem)
        .join(Meal, Meal.id == MealItem.meal_id)
        .where(
            Meal.user_id == user.id,
            Meal.eaten_at > cutoff,
            MealItem.food_id.is_not(None),
        )
    )
    rows = (await session.scalars(stmt)).all()
    return [str(r) for r in rows if r is not None]


def compute_deficit_node(state: RecommendState) -> RecommendState:
    """Pure Python: pick the macro with the largest *relative* deficit."""
    if state.get("error") or state.get("intent") == "freeform":
        return state

    consumed = state["today_totals"]
    targets = state["targets"]
    macros: list[tuple[DeficitMacro, float, float]] = [
        ("protein", consumed["protein_g"], targets["protein_g"]),
        ("fat", consumed["fat_g"], targets["fat_g"]),
        ("carbs", consumed["carbs_g"], targets["carbs_g"]),
    ]

    biggest_deficit_ratio = 0.0
    biggest: DeficitMacro = None
    biggest_grams = 0.0
    for macro, got, target in macros:
        if target <= 0:
            continue
        ratio_left = max(0.0, (target - got) / target)
        if ratio_left > biggest_deficit_ratio:
            biggest_deficit_ratio = ratio_left
            biggest = macro
            biggest_grams = max(0.0, target - got)

    # If everything is satisfied → push variety instead of deficit.
    if biggest is None or biggest_deficit_ratio < 0.10:
        state["intent"] = "variety"
        state["deficit_macro"] = None
        state["deficit_grams"] = 0.0
    else:
        state["intent"] = "deficit"
        state["deficit_macro"] = biggest
        state["deficit_grams"] = round(biggest_grams, 1)
    return state


async def retrieve_candidates_node(state: RecommendState) -> RecommendState:
    """Qdrant semantic search → top-20 candidate foods.

    Three queries are merged:
      (1) deficit-macro keyword (e.g. "богатый белком ужин") — direct fit
      (2) the user's favorite foods — for 'similar to what they like'
      (3) free-form query if intent=freeform
    Results from `llm_estimate` are excluded — they're unverified guesses.
    Recently-eaten food_ids are excluded for variety.
    """
    if state.get("error"):
        return state

    queries: list[tuple[str, float | None]] = []
    intent = state.get("intent", "deficit")
    deficit = state.get("deficit_macro")

    if intent == "freeform" and state.get("freeform_query"):
        queries.append((state["freeform_query"], None))
    elif intent == "deficit":
        queries.append((_deficit_query_text(deficit), _min_macro_threshold(deficit)))
    else:  # variety
        queries.append(("разнообразное здоровое блюдо", None))

    # Always blend in the user's taste — top-3 favorites as separate queries.
    for fav in state.get("favorite_food_names", [])[:3]:
        queries.append((f"что-то похожее на {fav}", None))

    exclude = state.get("recent_food_ids") or []
    seen: set[str] = set()
    merged: list[CandidateFood] = []
    for q, min_protein in queries:
        hits = await search_foods_semantic(
            q,
            limit=10,
            source_filter=["curated", "user_recipe", "off"],
            exclude_food_ids=exclude,
            min_protein_per_100=min_protein,
        )
        for h in hits:
            fid = h.get("food_id")
            if fid and fid not in seen:
                seen.add(fid)
                merged.append(h)  # type: ignore[arg-type]
        if len(merged) >= 20:
            break

    state["candidates"] = merged[:20]
    return state


def _deficit_query_text(macro: DeficitMacro) -> str:
    return {
        "protein": "богатый белком продукт высокобелковая еда",
        "fat": "источник полезных жиров",
        "carbs": "сложные углеводы крупы",
        "kcal": "калорийное питательное блюдо",
        None: "сбалансированное блюдо",
    }[macro]


def _min_macro_threshold(macro: DeficitMacro) -> float | None:
    """When chasing a macro deficit, require candidates to actually contain it."""
    if macro == "protein":
        return 10.0  # >=10g protein per 100g/per piece
    return None


_RECOMMEND_SYSTEM_PROMPT = """\
Ты — диетологический ассистент NutriSnap. На вход — состояние юзера на сегодня
(сколько съел, сколько ещё надо), его любимые продукты и top-20 кандидатов
из семантического поиска по каталогу. Твоя задача — выбрать ровно 3
рекомендации и для каждой написать ОДНО короткое (≤140 символов) обоснование
на русском, объясняющее ПОЧЕМУ именно эта еда сейчас (макро-добор, разнообразие,
вкус).

Правила:
- Каждый item ОБЯЗАН быть из переданного списка кандидатов (не выдумывай).
- `food_id` бери ИЗ кандидата как есть (UUID-строка).
- `suggested_grams` — реалистичная порция (для гречки/риса 150-200, для снеков 50-80,
  для творожков 100-150, для протеина 30г). Если у кандидата `metric != "g"`,
  всё равно ставь grams (для piece domain ≈ piece_weight_g).
- `kcal`, `protein_g`, `fat_g`, `carbs_g` ПЕРЕСЧИТАЙ под suggested_grams
  (значения в кандидате — per 100g).
- `summary` (2-3 предложения): сначала факт о сегодняшнем дне юзера
  ("ты уже съел 1450 ккал, осталось 600"), потом одно предложение про общий
  стиль рекомендаций (например, "добор белка" или "разнообразие").
- НЕ повторяй один и тот же продукт. НЕ давай 3 десерта подряд если день не закрыт.
"""


async def compose_recommendation_node(state: RecommendState) -> RecommendState:
    """LLM picks 3 candidates with rationale (structured output)."""
    if state.get("error") or not state.get("candidates"):
        state["recommendations"] = []
        state["summary"] = (
            "Пока мало данных для рекомендаций — залогай пару приёмов и попробуй снова."
        )
        return state

    client = get_openai_client()
    user_payload = _build_llm_user_payload(state)

    try:
        response = await client.beta.chat.completions.parse(
            model=settings.TEXT_MODEL,
            temperature=0.4,
            max_tokens=1200,
            response_format=RecommendationResult,
            messages=[
                {"role": "system", "content": _RECOMMEND_SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
        )
    except Exception as exc:
        logger.exception("Recommender LLM call failed")
        state["error"] = f"recommend LLM failed: {exc.__class__.__name__}"
        state["recommendations"] = []
        state["summary"] = ""
        return state

    parsed = response.choices[0].message.parsed
    if parsed is None:
        state["recommendations"] = []
        state["summary"] = ""
        return state

    state["recommendations"] = list(parsed.items)
    state["summary"] = parsed.summary
    return state


def _build_llm_user_payload(state: RecommendState) -> str:
    """Stuff state into a compact JSON-ish payload the LLM can ingest."""
    consumed = state["today_totals"]
    targets = state["targets"]
    lines: list[str] = []
    lines.append("СОСТОЯНИЕ ДНЯ:")
    lines.append(
        f"  Съедено: {consumed['kcal']:.0f} ккал / Б {consumed['protein_g']:.0f} / "
        f"Ж {consumed['fat_g']:.0f} / У {consumed['carbs_g']:.0f}  "
        f"(приёмов: {consumed['meals_count']})"
    )
    lines.append(
        f"  Цель:    {targets['kcal']} ккал / Б {targets['protein_g']} / "
        f"Ж {targets['fat_g']} / У {targets['carbs_g']}"
    )
    intent = state.get("intent", "deficit")
    if intent == "deficit" and state.get("deficit_macro"):
        lines.append(
            f"  Дефицит: {state['deficit_macro']} (нужно ещё ~{state['deficit_grams']:g} г)"
        )
    elif intent == "variety":
        lines.append("  Режим: разнообразие (день почти закрыт по макро)")
    elif intent == "freeform":
        lines.append(f"  Свободный запрос: {state.get('freeform_query', '')}")

    favs = state.get("favorite_food_names") or []
    if favs:
        lines.append(f"\nЛЮБИМЫЕ: {', '.join(favs)}")

    lines.append(f"\nКАНДИДАТЫ ({len(state['candidates'])} штук):")
    for i, c in enumerate(state["candidates"], 1):
        brand = f" [{c['brand']}]" if c.get("brand") else ""
        metric = c.get("metric", "g")
        lines.append(
            f"  {i}. food_id={c['food_id']} | {c['name']}{brand} "
            f"(per 100{metric}: {c['kcal']:.0f} ккал, "
            f"Б {c['protein_g']:.1f} / Ж {c['fat_g']:.1f} / У {c['carbs_g']:.1f}, "
            f"source={c.get('source')})"
        )

    return "\n".join(lines)


# ─── Graph build ──────────────────────────────────────────────────────────────


def build_recommender_graph():
    graph = StateGraph(RecommendState)
    graph.add_node("gather_user_state", gather_user_state_node)
    graph.add_node("compute_deficit", compute_deficit_node)
    graph.add_node("retrieve_candidates", retrieve_candidates_node)
    graph.add_node("compose_recommendation", compose_recommendation_node)

    graph.add_edge(START, "gather_user_state")
    graph.add_edge("gather_user_state", "compute_deficit")
    graph.add_edge("compute_deficit", "retrieve_candidates")
    graph.add_edge("retrieve_candidates", "compose_recommendation")
    graph.add_edge("compose_recommendation", END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_recommender_graph():
    """Singleton compiled recommender graph — one per process."""
    return build_recommender_graph()
