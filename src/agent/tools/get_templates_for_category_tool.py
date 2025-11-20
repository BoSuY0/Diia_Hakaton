from typing import Any, Dict, List

from src.agent.tools.registry import tool
from src.categories.index import TemplateInfo, list_templates, store as category_store
from src.common.logging import get_logger
from src.common.vsc import vsc_templates
from src.sessions.models import SessionState
from src.sessions.store import load_session, save_session

logger = get_logger(__name__)


def _category_ids() -> List[str]:
    try:
        return sorted(category_store.categories.keys())
    except Exception:
        return []


@tool(
    name="get_templates_for_category",
    description="Повертає список доступних шаблонів для обраної категорії. Використовує category_id з поточної сесії.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
            }
        },
        "required": ["session_id"],
        "additionalProperties": False,
    },
    format_result_func=vsc_templates
)
def get_templates_for_category_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    session_id = args["session_id"]
    
    # Get category_id from session
    try:
        session = load_session(session_id)
        category_id = session.category_id
        if not category_id:
            return {
                "ok": False,
                "error": "No category selected for this session. Please select a category first."
            }
    except Exception as e:
        logger.error("Failed to load session: %s", e)
        return {
            "ok": False,
            "error": "Session not found"
        }
    
    logger.info("tool=get_templates_for_category session_id=%s category_id=%s", session_id, category_id)
    templates: List[TemplateInfo] = list_templates(category_id)
    
    # Auto-select if only one template
    if len(templates) == 1:
        try:
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
