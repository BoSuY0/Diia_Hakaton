from typing import Any, Dict, List

from src.agent.tools.registry import tool
from src.categories.index import list_templates, store as category_store
from src.common.logging import get_logger
from src.sessions.models import SessionState
from src.sessions.store import load_session, save_session

logger = get_logger(__name__)


def _template_ids() -> List[str]:
    ids: set[str] = set()
    try:
        for category in category_store.categories.values():
            for t in list_templates(category.id):
                ids.add(t.id)
    except Exception:
        return []
    return sorted(ids)


@tool(
    name="set_template",
    description="Встановлює конкретний шаблон договору в межах обраної категорії.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "minLength": 1,
            },
            "template_id": {
                "type": "string",
                "minLength": 1,
            }
        },
        "required": ["session_id", "template_id"],
        "additionalProperties": False,
    }
)
def set_template_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    session_id = args["session_id"]
    template_id = args["template_id"]
    
    session = load_session(session_id)
    logger.info(
        "tool=set_template session_id=%s category_id=%s template_id=%s",
        session_id,
        session.category_id,
        template_id,
    )

    if not session.category_id:
        return {
            "ok": False,
            "error": "Спочатку потрібно обрати категорію (set_category).",
        }

    templates = {t.id: t for t in list_templates(session.category_id)}
    # Resolve template_id: allow passing name instead of ID
    if template_id not in templates:
        # Try to match by name (case-insensitive)
        matched = None
        for t in list_templates(session.category_id):
            if t.name.lower() == template_id.lower():
                matched = t.id
                break
        if matched:
            template_id = matched
        else:
            return {
                "ok": False,
                "error": "Шаблон не належить до обраної категорії.",
            }

    session.template_id = template_id
    session.state = SessionState.TEMPLATE_SELECTED
    save_session(session)

    return {
        "ok": True,
        "category_id": session.category_id,
        "template_id": template_id,
    }
