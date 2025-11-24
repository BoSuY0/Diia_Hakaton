import json

import asyncio
import pytest

from backend.api.tool_adapter import tool_router


@pytest.mark.asyncio
async def test_wrapper_tool_find_category():
    res = await tool_router.tool_find_category_by_query_async("q")
    assert isinstance(res, dict)


def test_tool_upsert_field_context_tags():
    called = {}

    class Dummy:
        def execute(self, args, ctx):
            called["ctx"] = ctx
            return {"ok": True}

        def format_result(self, r):
            return json.dumps(r)

    tool_router.tool_registry.register("upsert_field", Dummy())
    res = tool_router.tool_upsert_field("s1", "f", "v", tags={"[T]": "val"}, role=None, _context={"client_id": "u"})
    assert res["ok"] is True
    ctx = called["ctx"]
    assert ctx["tags"] == {"[T]": "val"}
    assert ctx["pii_tags"] == {"[T]": "val"}
    assert ctx["client_id"] == "u"
