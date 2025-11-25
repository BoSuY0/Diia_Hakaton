"""Tool registry for agent tools."""
from __future__ import annotations

from typing import Any, Optional, Type

from backend.agent.tools.base import BaseTool
from backend.shared.registry import Registry


class ToolRegistry(Registry[BaseTool]):
    """
    Registry specifically for BaseTool instances.
    """

    def register_tool(self, tool: BaseTool) -> BaseTool:
        """Register a tool instance."""
        return self.register(tool.name, tool)

    def get_definitions(self, minified: bool = True) -> list[dict[str, Any]]:
        """
        Generate OpenAI-compatible tool definitions for all registered tools.
        If minified is True, uses aliases and minimal parameter schemas to save tokens.
        """
        definitions = []
        for tool in self._registry.values():
            if minified:
                # Minimal spec: alias name, no param descriptions
                parameters = tool.parameters.copy()
                props = parameters.get("properties", {})
                min_props = {}
                for key, value in props.items():
                    # Skip session_id for LLM as it is injected
                    if key == "session_id":
                        continue
                    # Keep only type, remove description/title
                    min_props[key] = {"type": value.get("type", "string")}
                    if "enum" in value:
                        min_props[key]["enum"] = value["enum"]

                parameters["properties"] = min_props

                definitions.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.alias,
                            "parameters": parameters,
                        },
                    }
                )
            else:
                # Full spec
                definitions.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                )
        return definitions

    def get_by_alias(self, alias: str) -> Optional[BaseTool]:
        """
        Find a tool by its alias.
        """
        for tool in self._registry.values():
            if tool.alias == alias:
                return tool
        return None


# Global tool registry instance
tool_registry = ToolRegistry(name="GlobalToolRegistry")


def register_tool(cls: Type[BaseTool]) -> Type[BaseTool]:
    """
    Decorator to register a tool class.
    """
    instance = cls()
    tool_registry.register_tool(instance)
    return cls
