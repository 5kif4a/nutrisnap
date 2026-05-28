"""transcribe_voice_node — Whisper STT, then chain into text parser."""

from __future__ import annotations

import logging

from langsmith import traceable

from app.graph.state import GraphState
from app.services.openai_client import transcribe_voice

logger = logging.getLogger(__name__)


@traceable(run_type="chain", name="node_transcribe_voice")
async def transcribe_voice_node(state: GraphState) -> GraphState:
    audio = state.get("voice_bytes")
    if not audio:
        state["error"] = "no voice bytes in state"
        state["transcribed_text"] = ""
        return state

    try:
        text = await transcribe_voice(audio)
    except Exception as exc:
        logger.exception("Voice transcription failed")
        state["error"] = f"stt failed: {exc.__class__.__name__}"
        state["transcribed_text"] = ""
        return state

    state["transcribed_text"] = text
    # Feed the transcript into the text path so the parser handles it.
    state["text_input"] = text
    # Tag empty STT here — LangGraph drops state mutations performed in the
    # conditional-edge callback, so the routing function can only read.
    if not text.strip():
        state["error"] = "stt failed: empty"
    return state
