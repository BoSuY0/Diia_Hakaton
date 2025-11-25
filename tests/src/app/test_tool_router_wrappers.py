"""Tests for tool router wrapper functions."""
import json

import pytest

from backend.api.tool_adapter import tool_router


@pytest.mark.asyncio
async def test_wrapper_tool_find_category():
    """Test find category wrapper."""
    res = await tool_router.tool_find_category_by_query_async("q")
    assert isinstance(res, dict)


@pytest.mark.asyncio
async def test_wrapper_tool_find_category_async():
    """Test async find category wrapper."""
    res = await tool_router.tool_find_category_by_query_async("q")
    assert isinstance(res, dict)


def test_tool_upsert_field_context_tags():
    """Test upsert field context tags."""
    called = {}

    class Dummy:
        """Dummy tool for testing."""

        name = "upsert_field"

        def execute(self, _args, ctx):
            """Execute dummy tool."""
            called["ctx"] = ctx
            return {"ok": True}

        def format_result(self, r):
            """Format result."""
            return json.dumps(r)

    tool_router.tool_registry.register("upsert_field", Dummy())
    res = tool_router.tool_upsert_field(
        "s1", "f", "v", tags={"[T]": "val"}, role=None, _context={"user_id": "u"}
    )
    assert res["ok"] is True
    ctx = called["ctx"]
    assert ctx["tags"] == {"[T]": "val"}
    assert ctx["pii_tags"] == {"[T]": "val"}
    assert ctx["user_id"] == "u"
