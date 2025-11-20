from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

# Import tools to register them
import src.agent.tools.categories
import src.agent.tools.session
from src.agent.tools.registry import tool_registry
from src.common.config import settings
from src.common.logging import get_logger
from src.sessions.models import SessionState
from src.sessions.store import load_session

logger = get_logger(__name__)


# Generate tool definitions dynamically from the registry
TOOL_DEFINITIONS = tool_registry.get_definitions()


def dispatch_tool(
    name: str,
    arguments_json: str,
    tags: Dict[str, str] | None = None,
) -> str:
    """
    Execute tool by name and JSON-encoded arguments.
    Delegates to the ToolRegistry.
    """
    args = json.loads(arguments_json or "{}")
    logger.info("dispatch_tool name=%s", name)

    # Special handling for find_category_by_query was removed.
    # The tool should handle its own logic or the LLM should use the correct tool.

    tool = tool_registry.get(name)
    if not tool:
        logger.error("Tool not found: %s", name)
        return json.dumps({"error": f"Tool {name} not found"}, ensure_ascii=False)

    context = {"tags": tags}
    
    try:
        result = tool.execute(args, context)
        return tool.format_result(result)
    except Exception as e:
        logger.exception("Error executing tool %s", name)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# Re-export helper functions if they are still needed by server.py
# Ideally server.py should use the tools directly or via API endpoints, 
# but for now we keep these wrappers to avoid breaking server.py too much.

def tool_find_category_by_query(query: str) -> Dict[str, Any]:
    tool = tool_registry.get("find_category_by_query")
    if tool:
        return tool.execute({"query": query}, {})
    return {}

def tool_get_templates_for_category(category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_templates_for_category")
    if tool:
        return tool.execute({"category_id": category_id}, {})
    return {}

def tool_get_category_entities(category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_category_entities")
    if tool:
        return tool.execute({"category_id": category_id}, {})
    return {}

def tool_get_party_fields_for_session(session_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_party_fields_for_session")
    if tool:
        return tool.execute({"session_id": session_id}, {})
    return {}

def tool_set_category(session_id: str, category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("set_category")
    if tool:
        return tool.execute({"session_id": session_id, "category_id": category_id}, {})
    return {}

def tool_set_template(session_id: str, template_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("set_template")
    if tool:
        return tool.execute({"session_id": session_id, "template_id": template_id}, {})
    return {}

def tool_upsert_field(session_id: str, field: str, value: str, tags: Dict[str, str] | None = None, role: Optional[str] = None) -> Dict[str, Any]:
    tool = tool_registry.get("upsert_field")
    if tool:
        return tool.execute({"session_id": session_id, "field": field, "value": value, "role": role}, {"tags": tags})
    return {}

def tool_get_session_summary(session_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_session_summary")
    if tool:
        return tool.execute({"session_id": session_id}, {})
    return {}

def tool_build_contract(session_id: str, template_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("build_contract")
    if tool:
        return tool.execute({"session_id": session_id, "template_id": template_id}, {})
    return {}

def tool_set_party_context(session_id: str, role: str, person_type: str) -> Dict[str, Any]:
    tool = tool_registry.get("set_party_context")
    if not tool:
        logger.error("tool_set_party_context: Tool 'set_party_context' not found in registry!")
        return {"ok": False, "error": "Tool set_party_context not found"}
    
    logger.info("tool_set_party_context: Executing for session_id=%s", session_id)
    return tool.execute({"session_id": session_id, "role": role, "person_type": person_type}, {})
