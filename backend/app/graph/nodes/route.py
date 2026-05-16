"""route_input_node — pure-Python decision of which branch to take.

This is intentionally NOT an LLM call: PTB already tells us message type.
See docs/ARCHITECTURE_VARIANTS.md (Variant B — thin LangGraph).
"""

from __future__ import annotations

from app.graph.state import GraphState, InputType


def route_input(state: GraphState) -> str:
    """Return the next node name based on declared input type."""
    raw_type: InputType = state.get("raw_input_type", "unknown")  # type: ignore[assignment]
    if raw_type == "photo":
        return "analyze_photo"
    if raw_type == "voice":
        return "transcribe_voice"
    if raw_type in ("text", "forward"):
        return "parse_text"
    return "reject"
