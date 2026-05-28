"""Tests for the MCP client result parsing (`_as_dict`).

langchain-mcp-adapters returns a tool's structured result as a JSON string; the
node relies on `_as_dict` to coerce it (and a few other shapes) back to a dict.
"""

from __future__ import annotations

import pytest

from app.mcp.client import _as_dict


def test_as_dict_parses_json_string():
    assert _as_dict('{"found": true, "kcal": 165}') == {"found": True, "kcal": 165}


def test_as_dict_unwraps_text_content_block():
    # the shape langchain-mcp-adapters actually returns for a Pydantic result
    block = {"type": "text", "text": '{"ok": true, "kcal": 330.0}', "id": "lc_1"}
    assert _as_dict(block) == {"ok": True, "kcal": 330.0}


def test_as_dict_passes_through_dict():
    d = {"ok": True, "weight_g": 200}
    assert _as_dict(d) is d


def test_as_dict_takes_first_of_list():
    assert _as_dict(['{"ok": true}', "ignored"]) == {"ok": True}


def test_as_dict_rejects_unexpected_type():
    with pytest.raises(TypeError):
        _as_dict(42)
