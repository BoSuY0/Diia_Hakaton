import json

from src.app.tool_router import dispatch_tool


def test_dispatch_tool_handles_missing():
    res = dispatch_tool("no_such_tool", "{}", client_id=None)
    data = json.loads(res)
    assert "error" in data


def test_dispatch_tool_passes_context(monkeypatch):
    recorded = {}

    class DummyTool:
        name = "dummy"
        alias = "dummy"
        parameters = {"type": "object", "properties": {}}

        def execute(self, args, context):
            recorded["args"] = args
            recorded["context"] = context
            return {"ok": True, "args": args}

        def format_result(self, result):
            return json.dumps(result, ensure_ascii=False)

    monkeypatch.setattr(
        "src.app.tool_router.tool_registry.get",
        lambda name: DummyTool() if name == "dummy" else None,
    )

    res = dispatch_tool(
        "dummy",
        '{"foo": "bar"}',
        tags={"[T1]": "RAW"},
        client_id="user1",
    )
    data = json.loads(res)
    assert data["ok"] is True
    assert recorded["args"]["foo"] == "bar"
    ctx = recorded["context"]
    assert ctx["client_id"] == "user1"
    assert ctx["pii_tags"] == {"[T1]": "RAW"}
    assert ctx["tags"] == {"[T1]": "RAW"}
