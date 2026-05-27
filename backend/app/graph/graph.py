"""Compile the NutriSnap meal-logging LangGraph.

Graph (Variant B — thin LangGraph, see docs/ARCHITECTURE_VARIANTS.md):

    START
      │
      ▼
    route_input ── pure code; picks the branch by input type
      ├──[photo]── analyze_photo (vision + built-in guiderail in one call)
      │              ├── unsafe / non-food → error
      │              └── ok                 → nutrition_lookup
      ├──[voice]── transcribe_voice ──┐
      │                               ▼
      │                          guiderail
      │                               ├── blocked → error
      │                               └── ok      → parse_text
      │                                              ├── empty / parse fail → error
      │                                              └── items               → nutrition_lookup
      ├──[text]── guiderail (same as voice path)
      └──[unknown]── reject ── END

    nutrition_lookup ──┐
                       ├── nothing resolved → error
                       └── ok               → reflect
                                                ├── ok     → finalize ── END
                                                ├── retry  → nutrition_lookup (strict=True)
                                                └── giveup → error ── END

`guiderail` runs the OpenAI Moderation API and the food-intent classifier
in parallel. For photos, the same role is played by the vision call, which
returns `is_food_image`/`is_safe_image` in its structured schema.

`reflect` checks resolved items for hallucinations (Atwater + fuzzy
name-match + vision scene cross-check). On the first failure it loops back
to `nutrition_lookup` with `reflect_strict=True` (skip OFF/FatSecret text
search). On the second failure it routes to `error`.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.error import error_node
from app.graph.nodes.finalize import finalize_node, reject_node
from app.graph.nodes.guiderail import guiderail_node
from app.graph.nodes.nutrition import nutrition_fetch_node
from app.graph.nodes.parser import parse_text_node
from app.graph.nodes.reflect import reflect_node
from app.graph.nodes.route import route_input
from app.graph.nodes.transcribe import transcribe_voice_node
from app.graph.nodes.vision import analyze_photo_node
from app.graph.state import GraphState


def _route_after_vision(state: GraphState) -> str:
    if state.get("error"):
        return "error"
    if state.get("is_input_safe") is False:
        return "error"
    if not state.get("parsed_items"):
        # Vision returned no items even though the image was OK — tag and bail.
        state["error"] = "nothing parsed"
        return "error"
    return "nutrition_lookup"


def _route_after_transcribe(state: GraphState) -> str:
    if state.get("error"):
        return "error"
    if not (state.get("transcribed_text") or "").strip():
        state["error"] = "stt failed: empty"
        return "error"
    return "guiderail"


def _route_after_guiderail(state: GraphState) -> str:
    if state.get("is_input_safe") is False:
        return "error"
    return "parse_text"


def _route_after_parse(state: GraphState) -> str:
    if state.get("error"):
        return "error"
    if not state.get("parsed_items"):
        state["error"] = "nothing parsed"
        return "error"
    return "nutrition_lookup"


def _route_after_lookup(state: GraphState) -> str:
    if not state.get("resolved_items"):
        state["error"] = "nothing resolved"
        return "error"
    return "reflect"


def _route_after_reflect(state: GraphState) -> str:
    decision = state.get("reflect_decision")
    if decision == "retry":
        return "nutrition_lookup"
    if decision == "giveup":
        return "error"
    return "finalize"


def build_meal_graph():
    graph = StateGraph(GraphState)

    graph.add_node("analyze_photo", analyze_photo_node)
    graph.add_node("transcribe_voice", transcribe_voice_node)
    graph.add_node("guiderail", guiderail_node)
    graph.add_node("parse_text", parse_text_node)
    graph.add_node("nutrition_lookup", nutrition_fetch_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("error", error_node)
    graph.add_node("reject", reject_node)

    # Entrypoint — pure-code router by input type.
    graph.add_conditional_edges(
        START,
        route_input,
        {
            "analyze_photo": "analyze_photo",
            "transcribe_voice": "transcribe_voice",
            "parse_text": "guiderail",  # text path now starts with guiderail
            "reject": "reject",
        },
    )

    # Photo path — vision call gates by is_food_image / is_safe_image.
    graph.add_conditional_edges(
        "analyze_photo",
        _route_after_vision,
        {
            "nutrition_lookup": "nutrition_lookup",
            "error": "error",
        },
    )

    # Voice path: transcribe → guiderail → parse.
    graph.add_conditional_edges(
        "transcribe_voice",
        _route_after_transcribe,
        {
            "guiderail": "guiderail",
            "error": "error",
        },
    )

    # Guiderail (shared by text + voice).
    graph.add_conditional_edges(
        "guiderail",
        _route_after_guiderail,
        {
            "parse_text": "parse_text",
            "error": "error",
        },
    )

    # Parser → lookup or error.
    graph.add_conditional_edges(
        "parse_text",
        _route_after_parse,
        {
            "nutrition_lookup": "nutrition_lookup",
            "error": "error",
        },
    )

    # Lookup → reflect or error.
    graph.add_conditional_edges(
        "nutrition_lookup",
        _route_after_lookup,
        {
            "reflect": "reflect",
            "error": "error",
        },
    )

    # Reflect can loop back to lookup once (with strict=True) or terminate.
    graph.add_conditional_edges(
        "reflect",
        _route_after_reflect,
        {
            "nutrition_lookup": "nutrition_lookup",
            "finalize": "finalize",
            "error": "error",
        },
    )

    graph.add_edge("finalize", END)
    graph.add_edge("error", END)
    graph.add_edge("reject", END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_meal_graph():
    """Singleton compiled graph — compile once per process."""
    return build_meal_graph()
