from __future__ import annotations

import abc
import inspect
from typing import Any, Dict, Optional

from backend.shared.async_utils import run_sync


class BaseTool(abc.ABC):
    """
    Abstract base class for all tools.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """
        Canonical name of the tool (e.g. 'find_category_by_query').
        """
        pass

    @property
    def alias(self) -> str:
        """
        Short alias for the tool to save tokens (e.g. 'fc').
        Defaults to name if not overridden.
        """
        return self.name

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """
        Description of the tool for the LLM.
        """
        pass

    @property
    @abc.abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        JSON schema for the tool parameters.
        """
        pass

    @abc.abstractmethod
    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """
        Execute the tool logic (sync by default).
        Context may contain session_id, user_id, etc.
        """
        pass

    async def execute_async(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """
        Async wrapper that runs sync tools in the threadpool
        and awaits native-async implementations if present.
        """
        if inspect.iscoroutinefunction(self.execute):
            return await self.execute(args, context)  # type: ignore[misc]
        return await run_sync(self.execute, args, context)

    def format_result(self, result: Any) -> str:
        """
        Format the result for the LLM (e.g. convert to JSON or VSC).
        Default implementation returns JSON string.
        """
        import json
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
