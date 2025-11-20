from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Type, Union

from src.agent.tools.base import BaseTool
from src.common.registry import Registry


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], Any]
    alias: str
    format_result_func: Optional[Callable[[Any], str]] = None

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        return self.func(args, context)

    def format_result(self, result: Any) -> str:
        if self.format_result_func:
            return self.format_result_func(result)
        import json
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


class ToolRegistry(Registry[Union[BaseTool, ToolDefinition]]):
    """
    Registry for BaseTool instances and function-based ToolDefinitions.
    """

    def register_tool(self, tool: Union[BaseTool, ToolDefinition]) -> Union[BaseTool, ToolDefinition]:
        return self.register(tool.name, tool)

    def get_definitions(self, minified: bool = True) -> list[dict[str, Any]]:
        """
        Generate OpenAI-compatible tool definitions for all registered tools.
        If minified is True, uses aliases and minimal parameter schemas to save tokens.
        """
        definitions = []
        for tool in self._registry.values():
            # Handle both BaseTool and ToolDefinition
            name = tool.alias if hasattr(tool, "alias") else tool.name
            parameters = tool.parameters.copy()
            
            if minified:
                # Minimal spec: alias name, no param descriptions
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
                            "name": name,
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

    def get_by_alias(self, alias: str) -> Optional[Union[BaseTool, ToolDefinition]]:
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
    Decorator to register a tool class (legacy support).
    """
    instance = cls()
    tool_registry.register_tool(instance)
    return cls


def tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    alias: Optional[str] = None,
    format_result_func: Optional[Callable[[Any], str]] = None,
):
    """
    Decorator to register a function as a tool.
    """
    def decorator(func):
        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
            alias=alias or name,
            format_result_func=format_result_func,
        )
        tool_registry.register_tool(tool_def)
        return func
    return decorator
