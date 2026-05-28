"""In-app MCP client for the Nutrition server.

Opens a single persistent stdio session at FastAPI startup and loads the MCP
tools as LangChain tools (auto-traced in LangSmith). The LangGraph
`nutrition_fetch_node` resolves tools by name via `get_mcp_tool`.

A persistent session means one subprocess + one pipe for the process lifetime,
so tool calls are a local round-trip rather than a per-call subprocess spawn.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger(__name__)

_SERVER_NAME = "nutrition"
# backend/ root — the cwd the subprocess needs so `import app...` resolves.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

_exit_stack: AsyncExitStack | None = None
_tools_by_name: dict[str, BaseTool] = {}


def _server_connection() -> dict[str, Any]:
    # The stdio subprocess does NOT inherit the parent env by default, so pass
    # it through explicitly — the server needs DATABASE_URL / OPENAI_API_KEY etc.
    return {
        _SERVER_NAME: {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "app.mcp.server"],
            "env": dict(os.environ),
            "cwd": str(_BACKEND_ROOT),
        }
    }


async def start_nutrition_mcp() -> None:
    """Spawn the Nutrition MCP server and load its tools. Idempotent."""
    global _exit_stack  # pylint: disable=global-statement
    if _exit_stack is not None:
        return

    stack = AsyncExitStack()
    try:
        client = MultiServerMCPClient(_server_connection())
        session = await stack.enter_async_context(client.session(_SERVER_NAME))
        tools = await load_mcp_tools(session)
    except Exception:
        await stack.aclose()
        logger.exception("Failed to start Nutrition MCP server")
        raise

    _tools_by_name.clear()
    for tool in tools:
        _tools_by_name[tool.name] = tool
    _exit_stack = stack
    logger.info("Nutrition MCP ready — tools: %s", sorted(_tools_by_name))


async def stop_nutrition_mcp() -> None:
    """Close the MCP session and terminate the server subprocess."""
    global _exit_stack  # pylint: disable=global-statement
    if _exit_stack is None:
        return
    await _exit_stack.aclose()
    _exit_stack = None
    _tools_by_name.clear()


def get_mcp_tool(name: str) -> BaseTool:
    tool = _tools_by_name.get(name)
    if tool is None:
        raise RuntimeError(
            f"MCP tool '{name}' not loaded — call start_nutrition_mcp() at startup"
        )
    return tool


async def call_mcp_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Invoke an MCP tool and parse its result into a dict.

    The tool returns a Pydantic model; langchain-mcp-adapters surfaces it as a
    text content block (`{"type": "text", "text": "<json>"}`). `_as_dict`
    unwraps that back to the tool's structured dict.
    """
    raw = await get_mcp_tool(name).ainvoke(args)
    return _as_dict(raw)


def _as_dict(raw: Any) -> dict[str, Any]:
    # A text content block — the JSON payload lives in its "text" field.
    if isinstance(raw, dict) and raw.get("type") == "text" and "text" in raw:
        return json.loads(raw["text"])
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, (list, tuple)) and raw:
        # content-block list — take the first element
        return _as_dict(raw[0])
    raise TypeError(f"Unexpected MCP tool result type: {type(raw)!r}")
