from __future__ import annotations

import json
from typing import Any, Dict, Optional

# Import tools to register them
import backend.agent.tools.categories
import backend.agent.tools.session
from backend.agent.tools.registry import tool_registry
from backend.shared.logging import get_logger

logger = get_logger(__name__)


def dispatch_tool(
    name: str,
    arguments_json: str,
    tags: Dict[str, str] | None = None,
    client_id: str | None = None,
) -> str:
    args = json.loads(arguments_json or "{}")
    logger.info("dispatch_tool name=%s", name)

    tool = tool_registry.get(name)
    if not tool:
        logger.error("Tool not found: %s", name)
        return json.dumps({"error": f"Tool {name} not found"}, ensure_ascii=False)

    context = {
        "tags": tags,
        "pii_tags": tags or {},
        "client_id": client_id,
    }

    try:
        result = tool.execute(args, context)
        return tool.format_result(result)
    except Exception as e:
        logger.exception("Error executing tool %s", name)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def dispatch_tool_async(
    name: str,
    arguments_json: str,
    tags: Dict[str, str] | None = None,
    client_id: str | None = None,
) -> str:
    args = json.loads(arguments_json or "{}")
    logger.info("dispatch_tool_async name=%s", name)

    tool = tool_registry.get(name)
    if not tool:
        logger.error("Tool not found: %s", name)
        return json.dumps({"error": f"Tool {name} not found"}, ensure_ascii=False)

    context = {
        "tags": tags,
        "pii_tags": tags or {},
        "client_id": client_id,
    }

    try:
        result = await tool.execute_async(args, context)
        return tool.format_result(result)
    except Exception as e:
        logger.exception("Error executing tool %s", name)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


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


def tool_get_category_parties(category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_category_parties")
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


def tool_upsert_field(
    session_id: str,
    field: str,
    value: str,
    tags: Dict[str, str] | None = None,
    role: Optional[str] = None,
    _context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    tool = tool_registry.get("upsert_field")
    if tool:
        context = {"tags": tags, "pii_tags": tags or {}}
        if _context:
            context.update(_context)
        return tool.execute(
            {"session_id": session_id, "field": field, "value": value, "role": role},
            context,
        )
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


def tool_set_party_context(
    session_id: str, role: str, person_type: str, _context: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    tool = tool_registry.get("set_party_context")
    if not tool:
        logger.error("tool_set_party_context: Tool 'set_party_context' not found in registry!")
        return {"ok": False, "error": "Tool set_party_context not found"}

    logger.info("tool_set_party_context: Executing for session_id=%s", session_id)
    return tool.execute(
        {"session_id": session_id, "role": role, "person_type": person_type},
        _context or {},
    )


def tool_sign_contract(session_id: str, role: Optional[str] = None) -> Dict[str, Any]:
    tool = tool_registry.get("sign_contract")
    if tool:
        return tool.execute({"session_id": session_id, "role": role}, {})
    return {}


async def tool_find_category_by_query_async(query: str) -> Dict[str, Any]:
    tool = tool_registry.get("find_category_by_query")
    if tool:
        return await tool.execute_async({"query": query}, {})
    return {}


async def tool_get_templates_for_category_async(category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_templates_for_category")
    if tool:
        return await tool.execute_async({"category_id": category_id}, {})
    return {}


async def tool_get_category_entities_async(category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_category_entities")
    if tool:
        return await tool.execute_async({"category_id": category_id}, {})
    return {}


async def tool_get_category_parties_async(category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_category_parties")
    if tool:
        return await tool.execute_async({"category_id": category_id}, {})
    return {}


async def tool_get_party_fields_for_session_async(session_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_party_fields_for_session")
    if tool:
        return await tool.execute_async({"session_id": session_id}, {})
    return {}


async def tool_set_category_async(session_id: str, category_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("set_category")
    if tool:
        return await tool.execute_async({"session_id": session_id, "category_id": category_id}, {})
    return {}


async def tool_set_template_async(session_id: str, template_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("set_template")
    if tool:
        return await tool.execute_async({"session_id": session_id, "template_id": template_id}, {})
    return {}


async def tool_upsert_field_async(
    session_id: str,
    field: str,
    value: str,
    tags: Dict[str, str] | None = None,
    role: Optional[str] = None,
    _context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    tool = tool_registry.get("upsert_field")
    if tool:
        context = {"tags": tags, "pii_tags": tags or {}}
        if _context:
            context.update(_context)
        return await tool.execute_async(
            {"session_id": session_id, "field": field, "value": value, "role": role},
            context,
        )
    return {}


async def tool_get_session_summary_async(session_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("get_session_summary")
    if tool:
        return await tool.execute_async({"session_id": session_id}, {})
    return {}


async def tool_build_contract_async(session_id: str, template_id: str) -> Dict[str, Any]:
    tool = tool_registry.get("build_contract")
    if tool:
        return await tool.execute_async({"session_id": session_id, "template_id": template_id}, {})
    return {}


async def tool_set_party_context_async(
    session_id: str, role: str, person_type: str, _context: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    tool = tool_registry.get("set_party_context")
    if not tool:
        logger.error("tool_set_party_context_async: Tool 'set_party_context' not found in registry!")
        return {"ok": False, "error": "Tool set_party_context not found"}

    logger.info("tool_set_party_context_async: Executing for session_id=%s", session_id)
    return await tool.execute_async(
        {"session_id": session_id, "role": role, "person_type": person_type},
        _context or {},
    )

