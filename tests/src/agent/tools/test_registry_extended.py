"""Extended tests for tool registry."""
from backend.agent.tools.registry import ToolRegistry


class DummyTool:  # pylint: disable=too-few-public-methods
    """Dummy tool for testing."""

    name = "dummy"
    alias = "dm"
    description = "desc"
    parameters = {"type": "object", "properties": {}}

    def execute(self, args, context):  # pylint: disable=unused-argument
        """Execute dummy tool."""
        return {}

    def format_result(self, result):  # pylint: disable=unused-argument,no-self-use
        """Format result."""
        return "{}"


def test_tool_registry_definitions_minified():
    """Test tool registry definitions minified."""
    reg = ToolRegistry(name="Test")
    reg.register_tool(DummyTool())
    defs = reg.get_definitions(minified=True)
    assert defs[0]["function"]["name"] == "dm"  # alias
    assert defs[0]["function"]["parameters"]["properties"] == {}


def test_tool_registry_get_by_alias():
    """Test tool registry get by alias."""
    reg = ToolRegistry(name="Test")
    t = DummyTool()
    reg.register_tool(t)
    assert reg.get_by_alias("dm") is t
