"""finalize_node — builds a human-readable summary for the bot to send."""

from __future__ import annotations

from app.graph.state import GraphState


async def finalize_node(state: GraphState) -> GraphState:
    if state.get("error"):
        state["response_text"] = f"⚠️ {state['error']}"
        return state

    resolved = state.get("resolved_items") or []
    if not resolved:
        if state.get("is_food_related") is False:
            state["response_text"] = (
                "🥦 Я помогаю только с дневником питания. "
                "Пришли фото еды, голосовое или описание текстом."
            )
        else:
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
    lines.append("")
    lines.append("Куда записать?")

    state["response_text"] = "\n".join(lines)
    return state


async def reject_node(state: GraphState) -> GraphState:
    state["response_text"] = (
        "🥦 Я помогаю только с дневником питания.\n"
        "Пришли мне:\n"
        "  📸 фото\n  🎙 голосовое\n  ✏️ текст"
    )
    state["resolved_items"] = []
    return state
