"""ask_weight_node — reprompt the user when any parsed item lacks a weight.

The text parser flags items where the user gave no number (e.g. "рис" without
"150"). Instead of falling through to lookup → compute (which would fail on
serving↔grams conversion) or showing a generic "не смог распознать", we ask
the user to retype with the missing weight. No state stored — user resends.
"""

from __future__ import annotations

from langsmith import traceable

from app.graph.state import GraphState


def _ru_genitive(name: str) -> str:
    """Cheap nominative→genitive nudge for the question ('рис' → 'риса').

    LLM-quality declension would need a model call; this is a pragmatic
    heuristic that hits the common -а/-я/-ия endings without overreaching.
    Returns the original name if no rule matched — sounds slightly off but
    never wrong-meaning.
    """
    word = name.strip().lower()
    if not word:
        return name
    # Already feminine ending — change -а/-я to -ы/-и
    if word.endswith("а"):
        return word[:-1] + "ы"
    if word.endswith("я"):
        return word[:-1] + "и"
    # Masculine consonant ending — add -а
    if word[-1] not in "аеёиоуыэюяьъ":
        return word + "а"
    return name


@traceable(run_type="chain", name="node_ask_weight")
async def ask_weight_node(state: GraphState) -> GraphState:
    items = state.get("parsed_items") or []
    missing = [i for i in items if not getattr(i, "weight_provided", True)]

    if not missing:
        # Defensive — router should not have taken us here. Bail to generic msg.
        state["response_text"] = (
            "Не смог распознать вес. Напиши снова с граммами, например `рис 150`."
        )
        state["resolved_items"] = []
        return state

    if len(missing) == 1:
        item_name = missing[0].name
        example = f"{item_name.lower()} 150"
        question = (
            f"Сколько граммов {_ru_genitive(item_name)} ты съел?\n"
            f"Напиши снова с весом, например `{example}`."
        )
    else:
        names = ", ".join(_ru_genitive(i.name) for i in missing)
        first = missing[0].name.lower()
        question = (
            f"Уточни вес: {names}.\nНапиши снова с граммами, например `{first} 150`."
        )

    state["response_text"] = question
    # Don't write a meal — the user is going to retype.
    state["resolved_items"] = []
    return state
