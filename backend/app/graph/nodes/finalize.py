"""finalize_node — render the success summary the bot sends to the user.

Error paths never reach this node — they are routed to `error_node` instead.
"""

from __future__ import annotations

from langsmith import traceable

from app.graph.state import GraphState


@traceable(run_type="chain", name="node_finalize")
async def finalize_node(state: GraphState) -> GraphState:
    resolved = state.get("resolved_items") or []
    if not resolved:
        # Belt-and-braces: graph should have routed to error_node, but if we
        # got here with nothing to show, render a generic fallback.
        state["response_text"] = (
            "Не смог распознать продукты. Попробуй ещё раз — фото, голос или текст."
        )
        return state

    lines = ["📋 Распознал:"]
    total_kcal = 0.0
    total_p = 0.0
    total_f = 0.0
    total_c = 0.0
    for r in resolved:
        p = r["payload"]
        lines.append(
            f"• {p.food_name} — {p.amount:g} {p.unit.value} "
            f"({p.kcal:.0f} ккал, Б {p.protein_g:.0f} / Ж {p.fat_g:.0f} / У {p.carbs_g:.0f})"
        )
        total_kcal += p.kcal
        total_p += p.protein_g
        total_f += p.fat_g
        total_c += p.carbs_g

    lines.append("")
    lines.append(
        f"Итого: {total_kcal:.0f} ккал | Б {total_p:.0f} / Ж {total_f:.0f} / У {total_c:.0f}"
    )

    warnings = state.get("reflect_warnings") or []
    if warnings:
        # Show only the count + first warning so the user knows to double-check
        # without us flooding the chat with debugging detail.
        lines.append("")
        lines.append(f"⚠️ Низкая уверенность: {warnings[0]}")

    lines.append("")
    lines.append("Куда записать?")

    state["response_text"] = "\n".join(lines)
    return state


@traceable(run_type="chain", name="node_reject")
async def reject_node(state: GraphState) -> GraphState:
    state["response_text"] = (
        "🥦 Я помогаю только с дневником питания.\n"
        "Пришли мне:\n"
        "  📸 фото\n  🎙 голосовое\n  ✏️ текст"
    )
    state["resolved_items"] = []
    return state
