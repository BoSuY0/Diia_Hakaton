from __future__ import annotations

import abc
from typing import Any, Dict, Optional


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
        Execute the tool logic.
        Context may contain session_id, user_id, etc.
        """
        pass

    def format_result(self, result: Any) -> str:
        """
        Format the result for the LLM (e.g. convert to JSON or VSC).
        Default implementation returns JSON string.
        """
        import json
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
