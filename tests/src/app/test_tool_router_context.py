"""Tests for tool router context."""
import json

from backend.api.tool_adapter.tool_router import dispatch_tool


def test_dispatch_tool_handles_missing():
    """Test dispatch tool handles missing."""
    res = dispatch_tool("no_such_tool", "{}", user_id=None)
    data = json.loads(res)
    assert "error" in data


def test_dispatch_tool_passes_context(monkeypatch):
    """Test dispatch tool passes context."""
    recorded = {}

    class DummyTool:  # pylint: disable=too-few-public-methods
        """Dummy tool for testing."""

        name = "dummy"
        alias = "dummy"
        parameters = {"type": "object", "properties": {}}

        def execute(self, args, context):
            """Execute dummy tool."""
            recorded["args"] = args
            recorded["context"] = context
            return {"ok": True, "args": args}

        def format_result(self, result):
            """Format result."""
            return json.dumps(result, ensure_ascii=False)

    monkeypatch.setattr(
        "backend.api.tool_adapter.tool_router.tool_registry.get",
        lambda name: DummyTool() if name == "dummy" else None,
    )

    res = dispatch_tool(
        "dummy",
        '{"foo": "bar"}',
        tags={"[T1]": "RAW"},
        user_id="user1",
    )
    data = json.loads(res)
    assert data["ok"] is True
    assert recorded["args"]["foo"] == "bar"
    ctx = recorded["context"]
    assert ctx["user_id"] == "user1"
    assert ctx["pii_tags"] == {"[T1]": "RAW"}
    assert ctx["tags"] == {"[T1]": "RAW"}
