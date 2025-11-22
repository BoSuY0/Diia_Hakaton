from typing import Any, Dict, Optional

from src.agent.tools.registry import tool
from src.categories.index import Category, find_category_by_query
from src.common.logging import get_logger
from src.sessions.models import SessionState
from src.sessions.store import get_or_create_session, save_session

logger = get_logger(__name__)


@tool(
    name="find_category_by_query",
    description=(
        "Знаходить категорію договорів за текстовим запитом користувача (без PII). "
        "Спочатку використовує локальний пошук по назвах категорій."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
            },
            "session_id": {
                "type": "string",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }
)
def find_category_by_query_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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
    
    # Auto-set category if session_id is present
    session_id = args.get("session_id")
    if session_id:
        try:
            session = get_or_create_session(session_id)
            
            # Check if already selected to prevent loops
            if session.category_id == category.id and session.state != SessionState.IDLE:
                 return {
                     "category_id": category.id,
                     "label": category.label,
                     "already_configured": True,
                     "role": session.role,
                     "person_type": session.person_type,
                     "info": f"Category '{category.label}' already selected with role='{session.role}' and person_type='{session.person_type}'. Ask user if they want to continue or start fresh."
                 }

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
