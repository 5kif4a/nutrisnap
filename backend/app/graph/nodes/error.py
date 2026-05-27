"""error_node — render a user-facing message for any failure path.

The graph routes here on three classes of failure:
  1. Guiderail block (`state["guiderail_block_reason"]` set by guiderail or vision).
  2. Pipeline error (`state["error"]` set by vision/transcribe/parse/lookup).
  3. Reflect giveup (`state["error"] == "reflect failed"`).

Internal error tags stay in logs / LangSmith; only the friendly message
goes to the user.
"""

from __future__ import annotations

from langsmith import traceable

from app.graph.state import GraphState

_BLOCK_MESSAGES = {
    "non_food": (
        "🥦 Я помогаю только с дневником питания.\n"
        "Пришли фото еды, голосовое или описание текстом."
    ),
    "unsafe": (
        "🚫 Не могу обработать это сообщение.\nПришли что-нибудь по теме питания."
    ),
    "abuse": ("🚫 Давай по теме питания — пришли еду фото / голосом / текстом."),
    "inedible": ("🥦 Это не еда. Пришли что-нибудь съедобное."),
    "greeting": (
        "🥦 Я бот-дневник питания. Пришли:\n"
        "  📸 фото еды\n  🎙 голосовое\n  ✏️ текст с граммами"
    ),
    "nonsense": ("🤔 Не понял. Пришли еду — фото, голосовое или текст с граммами."),
    "empty_photo": ("🙃 Фото не загрузилось. Попробуй ещё раз."),
}


def _from_error_tag(err: str) -> str:
    if err.startswith("vision failed"):
        return (
            "🙃 Не получилось распознать фото.\n"
            "Сними поближе и в лучшем свете — или опиши текстом."
        )
    if err.startswith("stt failed"):
        return "🙃 Не разобрал голосовое.\nПопробуй ещё раз или опиши текстом."
    if err.startswith("parse failed"):
        return (
            "🙃 Не получилось обработать сообщение.\n"
            "Попробуй ещё раз через минуту или пришли фото / голосовое."
        )
    if err == "empty text input":
        return "Пришли мне еду — фото, голосовое или текст."
    if err.startswith("nutrition failed"):
        return (
            "🙃 Не смог посчитать КБЖУ.\n"
            "Попробуй ещё раз — иногда внешние сервисы тормозят."
        )
    if err == "reflect failed":
        return (
            "🤔 Не смог надёжно распознать продукты — цифры не сошлись.\n"
            "Попробуй переформулировать или указать бренд / штрих-код."
        )
    if err == "nothing parsed":
        return (
            "🙃 Не смог распознать продукты.\n"
            "Попробуй ещё раз — фото, голос или текст с граммами."
        )
    if err == "nothing resolved":
        return (
            "🙃 Не нашёл этих продуктов в базах.\n"
            "Попробуй уточнить название или пришли штрих-код / фото упаковки."
        )
    return "🙃 Что-то пошло не так.\nПопробуй ещё раз через минуту."


@traceable(run_type="chain", name="node_error")
async def error_node(state: GraphState) -> GraphState:
    reason = state.get("guiderail_block_reason")
    if reason:
        state["response_text"] = _BLOCK_MESSAGES.get(
            reason, _BLOCK_MESSAGES["non_food"]
        )
        state["resolved_items"] = []
        return state

    err = state.get("error") or ""
    state["response_text"] = _from_error_tag(err)
    state["resolved_items"] = []
    return state
