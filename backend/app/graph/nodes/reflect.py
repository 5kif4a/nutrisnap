"""reflect_node — anti-hallucination check on resolved meal items.

Runs three sanity checks per resolved item:
  1. Atwater: kcal ≈ 4·P + 9·F + 4·C (±50%). Catches macros that don't add up.
  2. Name match: SequenceMatcher ratio between user's parsed name and the
     matched food name. Catches OFF text-search mismatches (e.g. "Nuts 66"
     pulling some random nut-butter row). Skipped when the parser saw a
     barcode (barcode is ground truth).
  3. Scene cross-check (photo path only): the vision scene description
     should share a substantive token with the matched food name. Adds a
     warning when it doesn't, but doesn't block on its own.

Decision routed via `state["reflect_decision"]`:
  - "ok"     → resolved items pass → finalize
  - "retry"  → first failure → set reflect_strict=True, loop back to lookup
  - "giveup" → already retried once → error_node
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from langsmith import traceable

from app.db.models import FoodSource
from app.graph.state import GraphState

logger = logging.getLogger(__name__)

_NAME_MATCH_THRESHOLD = 0.35  # generous — only catches really wild mismatches
_ATWATER_LOW = 0.5
_ATWATER_HIGH = 1.5
_STOPWORDS = {
    "и",
    "с",
    "в",
    "на",
    "из",
    "от",
    "the",
    "of",
    "a",
    "an",
    "or",
    "and",
    "with",
    "for",
}


def _atwater_ok(kcal: float, protein_g: float, fat_g: float, carbs_g: float) -> bool:
    if kcal <= 0:
        return False
    derived = 4 * protein_g + 9 * fat_g + 4 * carbs_g
    if derived <= 0:
        # Some real foods are nearly pure water/fiber → kcal can be very low.
        # Only flag when there's a real kcal claim but no macros to back it.
        return kcal < 5
    ratio = derived / kcal
    return _ATWATER_LOW <= ratio <= _ATWATER_HIGH


def _name_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _tokens(text: str) -> set[str]:
    return {
        t
        for t in re.split(r"[^\wа-яА-ЯёЁ]+", text.lower())
        if len(t) > 3 and t not in _STOPWORDS
    }


@traceable(run_type="chain", name="node_reflect")
async def reflect_node(state: GraphState) -> GraphState:
    resolved = state.get("resolved_items") or []
    parsed = state.get("parsed_items") or []
    scene = state.get("vision_scene") or ""
    warnings: list[str] = []

    # Pair resolved items back to their parsed counterparts by index. Resolved
    # may be shorter (skipped items) — that's OK, we still validate what we have.
    suspect = False
    for idx, r in enumerate(resolved):
        payload = r["payload"]
        source = r["source"]

        if not _atwater_ok(
            payload.kcal, payload.protein_g, payload.fat_g, payload.carbs_g
        ):
            warnings.append(
                f"{payload.food_name}: macros don't add up (kcal vs 4P+9F+4C off by >50%)"
            )
            suspect = True

        # Name match — skip when barcode dominated the lookup or source is LLM.
        parsed_item = parsed[idx] if idx < len(parsed) else None
        had_barcode = bool(parsed_item and parsed_item.barcode)
        if (
            not had_barcode
            and source != FoodSource.LLM_ESTIMATE
            and parsed_item is not None
        ):
            ratio = _name_ratio(parsed_item.name, payload.food_name)
            if ratio < _NAME_MATCH_THRESHOLD:
                warnings.append(
                    f"{payload.food_name}: name diverges from '{parsed_item.name}' "
                    f"(ratio={ratio:.2f})"
                )
                suspect = True

        # Scene cross-check — informational only. A photo of "куриная грудка с
        # рисом" matched to "печенье" is suspect; raise a warning but don't
        # force a retry on this alone (vision_scene is one sentence and may
        # legitimately miss small items).
        if scene and parsed_item is not None:
            scene_tokens = _tokens(scene)
            name_tokens = _tokens(payload.food_name) | _tokens(parsed_item.name)
            if scene_tokens and name_tokens and not (scene_tokens & name_tokens):
                warnings.append(
                    f"{payload.food_name}: not mentioned in scene '{scene}'"
                )

    state["reflect_warnings"] = warnings

    if not suspect:
        state["reflect_decision"] = "ok"
        return state

    attempt = int(state.get("reflect_attempt") or 0)
    if attempt < 1:
        logger.info(
            "reflect: suspect items, retrying with strict=True; warnings=%s", warnings
        )
        state["reflect_attempt"] = attempt + 1
        state["reflect_strict"] = True
        state["reflect_decision"] = "retry"
        return state

    logger.warning(
        "reflect: still suspect after retry, giving up; warnings=%s", warnings
    )
    state["reflect_decision"] = "giveup"
    state["error"] = "reflect failed"
    return state
