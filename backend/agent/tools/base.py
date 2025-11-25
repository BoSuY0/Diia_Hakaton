"""Base class for AI agent tools."""
from __future__ import annotations

import abc
import json
from typing import Any, Dict


class BaseTool(abc.ABC):
    """Abstract base class for all tools."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Canonical name of the tool (e.g. 'find_category_by_query')."""

    @property
    def alias(self) -> str:
        """Short alias for the tool to save tokens (e.g. 'fc')."""
        return self.name

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Description of the tool for the LLM."""

    @property
    @abc.abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON schema for the tool parameters."""

    @abc.abstractmethod
    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """Execute the tool logic asynchronously."""

    async def execute_async(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """Alias for execute() for backward compatibility."""
        return await self.execute(args, context)

    def format_result(self, result: Any) -> str:
        """Format the result for the LLM (e.g. convert to JSON or VSC)."""
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
