"""Compile the NutriSnap meal-logging LangGraph.

Graph (Variant B — thin LangGraph, see docs/ARCHITECTURE_VARIANTS.md):

    START
      │
      ▼
    route (pure-Python conditional edge)
      ├──[photo]── analyze_photo ──┐
      ├──[voice]── transcribe_voice ── parse_text ─┐
      ├──[text]──────────────────── parse_text ────┤
      └──[unknown]── reject ────────────────────── END
                                                   │
                                                   ▼
                                          nutrition_fetch
                                                   │
                                                   ▼
                                              finalize
                                                   │
                                                   ▼
                                                  END

A conditional edge after `parse_text` short-circuits to `finalize` when
`is_food_related == False`, demonstrating real branching as required by
the course rubric.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.finalize import finalize_node, reject_node
from app.graph.nodes.nutrition import nutrition_fetch_node
from app.graph.nodes.parser import parse_text_node
from app.graph.nodes.route import route_input
from app.graph.nodes.transcribe import transcribe_voice_node
from app.graph.nodes.vision import analyze_photo_node
from app.graph.state import GraphState


def _route_after_parse(state: GraphState) -> str:
    """Skip lookup if the message was not food-related."""
    if state.get("is_food_related") is False:
        return "finalize"
    if not state.get("parsed_items"):
        return "finalize"
    return "nutrition_fetch"


def build_meal_graph():
    graph = StateGraph(GraphState)

    graph.add_node("analyze_photo", analyze_photo_node)
    graph.add_node("transcribe_voice", transcribe_voice_node)
    graph.add_node("parse_text", parse_text_node)
    graph.add_node("nutrition_fetch", nutrition_fetch_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("reject", reject_node)

    # Entrypoint — route based on input type (pure code, no LLM).
    graph.add_conditional_edges(
        START,
        route_input,
        {
            "analyze_photo": "analyze_photo",
            "transcribe_voice": "transcribe_voice",
            "parse_text": "parse_text",
            "reject": "reject",
        },
    )

    # Voice → parser (Whisper output feeds the text path).
    graph.add_edge("transcribe_voice", "parse_text")

    # Vision goes straight to lookup — items are already structured.
    graph.add_edge("analyze_photo", "nutrition_fetch")

    # Parser branches: food-related → lookup, else → straight to finalize.
    graph.add_conditional_edges(
        "parse_text",
        _route_after_parse,
        {
            "nutrition_fetch": "nutrition_fetch",
            "finalize": "finalize",
        },
    )

    graph.add_edge("nutrition_fetch", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("reject", END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_meal_graph():
    """Singleton compiled graph — compile once per process."""
    return build_meal_graph()
