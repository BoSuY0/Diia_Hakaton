from typing import Any, Dict, List, Optional

from src.agent.tools.registry import tool
from src.categories.index import Category, store as category_store
from src.common.logging import get_logger
from src.sessions.models import SessionState
from src.sessions.store import get_or_create_session, save_session

logger = get_logger(__name__)


def _category_ids() -> List[str]:
    try:
        return sorted(category_store.categories.keys())
    except Exception:
        return []


@tool(
    name="set_category",
    description="Встановлює для сесії обрану категорію договорів.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "minLength": 1,
            },
            "category_id": {
                "type": "string",
                "minLength": 1,
            }
        },
        "required": ["session_id", "category_id"],
        "additionalProperties": False,
    }
)
def set_category_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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
