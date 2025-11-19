from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agent.tools.base import BaseTool
from src.agent.tools.registry import register_tool
from src.categories.index import (
    Category,
    Entity,
    TemplateInfo,
    find_category_by_query,
    list_entities,
    list_templates,
    store as category_store,
)
from src.common.logging import get_logger
from src.sessions.models import SessionState
from src.sessions.store import get_or_create_session, save_session

logger = get_logger(__name__)


def _category_ids() -> List[str]:
    try:
        return sorted(category_store.categories.keys())
    except Exception:
        return []


@register_tool
class FindCategoryByQueryTool(BaseTool):
    @property
    def name(self) -> str:
        return "find_category_by_query"

    @property
    def description(self) -> str:
        return (
            "Знаходить категорію договорів за текстовим запитом користувача (без PII). "
            "Спочатку використовує локальний пошук по назвах категорій."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        query = (args.get("query") or "").strip()
        logger.info('tool=find_category_by_query query="%s"', query)

        if not query:
            return {"category_id": None}

        category: Optional[Category] = find_category_by_query(query)

        if not category:
            logger.info("tool=find_category_by_query no_match")
            return {"category_id": None}

        logger.info(
            "tool=find_category_by_query matched category_id=%s label=%s",
            category.id,
            category.label,
        )
        
        # Auto-set category if session_id is present (as per original logic)
        session_id = args.get("session_id")
        if session_id:
             try:
                # We can call the set_category logic directly or via the tool.
                # Here we duplicate the logic slightly to avoid circular dependency or complex dispatch.
                # Or better: we just return the result and let the LLM/Router handle it?
                # The original code had a side-effect in dispatch_tool. 
                # For now, let's keep it pure here and handle side-effects in the router or a "post-execute" hook?
                # Actually, the original code did: "if category found, auto set_category".
                # Let's replicate that side effect here for now.
                session = get_or_create_session(session_id)
                session.category_id = category.id
                session.template_id = None
                session.state = SessionState.CATEGORY_SELECTED
                session.party_fields.clear()
                session.contract_fields.clear()
                session.can_build_contract = False
                session.progress = {}
                save_session(session)
             except Exception as e:
                 logger.error(f"Failed to auto-set category: {e}")

        return {"category_id": category.id, "label": category.label}


@register_tool
class GetTemplatesForCategoryTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_templates_for_category"

    @property
    def description(self) -> str:
        return "Повертає список доступних шаблонів для обраної категорії."

    @property
    def parameters(self) -> Dict[str, Any]:
        ids = _category_ids()
        return {
            "type": "object",
            "properties": {
                "category_id": (
                    {
                        "type": "string",
                        "enum": ids,
                    }
                    if ids
                    else {
                        "type": "string",
                        "minLength": 1,
                    }
                )
            },
            "required": ["category_id"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        category_id = args["category_id"]
        logger.info("tool=get_templates_for_category category_id=%s", category_id)
        templates: List[TemplateInfo] = list_templates(category_id)
        
        # Auto-select if only one template (original logic)
        session_id = args.get("session_id")
        if session_id and len(templates) == 1:
             try:
                from src.sessions.store import load_session
                session = load_session(session_id)
                # Only set if matches category
                if session.category_id == category_id:
                    session.template_id = templates[0].id
                    session.state = SessionState.TEMPLATE_SELECTED
                    save_session(session)
                    logger.info("Auto-selected single template: %s", templates[0].id)
             except Exception:
                 pass

        return {
            "category_id": category_id,
            "templates": [{"id": t.id, "name": t.name} for t in templates],
        }

    def format_result(self, result: Any) -> str:
        from src.common.vsc import vsc_templates
        return vsc_templates(result)


@register_tool
class GetCategoryEntitiesTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_category_entities"

    @property
    def description(self) -> str:
        return "Повертає список полів (entities), які потрібно заповнити для категорії."

    @property
    def parameters(self) -> Dict[str, Any]:
        ids = _category_ids()
        return {
            "type": "object",
            "properties": {
                "category_id": (
                    {
                        "type": "string",
                        "enum": ids,
                    }
                    if ids
                    else {
                        "type": "string",
                        "minLength": 1,
                    }
                )
            },
            "required": ["category_id"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        category_id = args["category_id"]
        logger.info("tool=get_category_entities category_id=%s", category_id)
        
        try:
            entities: List[Entity] = list_entities(category_id)
        except ValueError:
            # Fallback logic from original code
            fixed_category_id: Optional[str] = None
            for category in category_store.categories.values():
                for t in list_templates(category.id):
                    if t.id == category_id:
                        fixed_category_id = category.id
                        break
                if fixed_category_id:
                    break
            if not fixed_category_id:
                raise
            logger.info(
                "tool=get_category_entities fix_template_id template_id=%s -> category_id=%s",
                category_id,
                fixed_category_id,
            )
            entities = list_entities(fixed_category_id)
            category_id = fixed_category_id

        return {
            "category_id": category_id,
            "entities": [
                {
                    "field": e.field,
                    "label": e.label,
                    "type": e.type,
                    "required": e.required,
                }
                for e in entities
            ],
        }

    def format_result(self, result: Any) -> str:
        from src.common.vsc import vsc_entities
        return vsc_entities(result)


@register_tool
class SetCategoryTool(BaseTool):
    @property
    def name(self) -> str:
        return "set_category"

    @property
    def description(self) -> str:
        return "Встановлює для сесії обрану категорію договорів."

    @property
    def parameters(self) -> Dict[str, Any]:
        ids = _category_ids()
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "minLength": 1,
                },
                "category_id": (
                    {
                        "type": "string",
                        "enum": ids,
                    }
                    if ids
                    else {
                        "type": "string",
                        "minLength": 1,
                    }
                )
            },
            "required": ["session_id", "category_id"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        category_id = args["category_id"]
        logger.info("tool=set_category session_id=%s category_id=%s", session_id, category_id)
        
        session = get_or_create_session(session_id)
        category: Optional[Category] = category_store.get(category_id)
        
        if not category:
            return {
                "ok": False,
                "error": "Невідома категорія договорів.",
            }

        session.category_id = category_id
        session.template_id = None
        session.state = SessionState.CATEGORY_SELECTED
        session.party_fields.clear()
        session.contract_fields.clear()
        session.can_build_contract = False
        session.progress = {}
        save_session(session)

        return {
            "ok": True,
            "category_id": category_id,
        }
