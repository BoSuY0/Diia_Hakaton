from backend.agent.tools.registry import ToolRegistry


class DummyTool:
    name = "dummy"
    alias = "dm"
    description = "desc"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, context):
        return {}

    def format_result(self, result):
        return "{}"


def test_tool_registry_definitions_minified():
    reg = ToolRegistry(name="Test")
    reg.register_tool(DummyTool())
    defs = reg.get_definitions(minified=True)
    assert defs[0]["function"]["name"] == "dm"  # alias
    assert defs[0]["function"]["parameters"]["properties"] == {}


def test_tool_registry_get_by_alias():
    reg = ToolRegistry(name="Test")
    t = DummyTool()
    reg.register_tool(t)
    assert reg.get_by_alias("dm") is t
