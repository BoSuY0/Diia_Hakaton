"""Category-related tools for the agent."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.tools.base import BaseTool
from backend.agent.tools.registry import register_tool
from backend.agent.tools.schema_helpers import (
    string_enum_or_minlength,
    session_id_property,
)
from backend.domain.categories.index import (
    Category,
    Entity,
    TemplateInfo,
    find_category_by_query,
    get_party_schema,
    list_entities,
    list_templates,
    store as category_store,
)
from backend.shared.logging import get_logger
from backend.infra.persistence.store import (
    aget_or_create_session,
    atransactional_session,
)

logger = get_logger(__name__)


def _category_ids() -> List[str]:
    """Get sorted list of category IDs."""
    try:
        return sorted(category_store.categories.keys())
    except (AttributeError, TypeError):
        return []


@register_tool
class FindCategoryByQueryTool(BaseTool):
    """Tool to find category by user query."""

    @property
    def name(self) -> str:
        return "find_category_by_query"

    @property
    def description(self) -> str:
        return (
            "ОБОВ'ЯЗКОВО використовуйте цей інструмент ПЕРШИМ кроком "
            "для пошуку категорії договору. Він підбирає категорію за запитом користувача."
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

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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

        return {"category_id": category.id, "label": category.label}


@register_tool
class GetTemplatesForCategoryTool(BaseTool):
    """Tool to get templates for a category."""

    @property
    def name(self) -> str:
        return "get_templates_for_category"

    @property
    def description(self) -> str:
        return (
            "Повертає список доступних шаблонів для обраної категорії."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category_id": string_enum_or_minlength(_category_ids()),
            },
            "required": ["category_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        category_id = args["category_id"]
        logger.info("tool=get_templates_for_category category_id=%s", category_id)
        templates: List[TemplateInfo] = list_templates(category_id)

        # Якщо є лише 1 шаблон - автоматично встановлюємо його
        auto_selected = False
        selected_template = None
        session_id = context.get("session_id")
        
        if len(templates) == 1 and session_id:
            selected_template = templates[0]
            try:
                from backend.infra.persistence.store import transactional_session
                from backend.domain.services.session import set_session_template
                with transactional_session(session_id) as session:
                    if session.category_id == category_id:
                        set_session_template(session, selected_template.id)
                        auto_selected = True
                        logger.info("Auto-selected single template: %s", selected_template.id)
            except Exception as e:
                logger.warning("Failed to auto-select template: %s", e)

        return {
            "category_id": category_id,
            "templates": [{"id": t.id, "name": t.name} for t in templates],
            "auto_selected": auto_selected,
            "selected_template_id": selected_template.id if auto_selected else None,
            "selected_template_name": selected_template.name if auto_selected else None,
        }

    def format_result(self, result: Any) -> str:
        """Format result for display."""
        from backend.shared.vsc import vsc_templates  # pylint: disable=import-outside-toplevel
        return vsc_templates(result)


@register_tool
class GetCategoryEntitiesTool(BaseTool):
    """Tool to get category entities (fields)."""

    @property
    def name(self) -> str:
        return "get_category_entities"

    @property
    def description(self) -> str:
        return "Повертає список полів (entities), які потрібно заповнити для категорії."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category_id": string_enum_or_minlength(_category_ids()),
            },
            "required": ["category_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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
        """Format result for display."""
        from backend.shared.vsc import vsc_entities  # pylint: disable=import-outside-toplevel
        return vsc_entities(result)


@register_tool
class GetCategoryPartiesTool(BaseTool):
    """Tool to get category parties (roles)."""

    @property
    def name(self) -> str:
        return "get_category_parties"

    @property
    def description(self) -> str:
        return "Повертає список ролей договору та полів для доступних типів осіб у категорії."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category_id": string_enum_or_minlength(_category_ids()),
            },
            "required": ["category_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        category_id = args["category_id"]
        return get_party_schema(category_id)


@register_tool
class SetCategoryTool(BaseTool):
    """Tool to set category for a session."""

    @property
    def name(self) -> str:
        return "set_category"

    @property
    def description(self) -> str:
        return "Встановлює для сесії обрану категорію договорів."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": session_id_property(),
                "category_id": string_enum_or_minlength(_category_ids()),
            },
            "required": ["session_id", "category_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        category_id = args["category_id"]

        logger.info("tool=set_category session_id=%s category_id=%s", session_id, category_id)

        # pylint: disable=import-outside-toplevel
        from backend.domain.sessions.actions import set_session_category

        # Гарантуємо, що файл сесії існує, щоб transactional_session не впав із 404
        await aget_or_create_session(session_id)

        template_id = None
        async with atransactional_session(session_id) as session:
            ok = set_session_category(session, category_id)
            # Отримуємо template_id, якщо він був автоматично обраний
            template_id = session.template_id

        if not ok:
            return {
                "ok": False,
                "error": "Невідома категорія договорів.",
            }

        result = {
            "ok": True,
            "category_id": category_id,
        }
        # Повертаємо template_id, якщо він був автоматично обраний
        if template_id:
            result["template_id"] = template_id
            result["template_auto_selected"] = True
        return result
