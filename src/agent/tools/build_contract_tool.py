from typing import Any, Dict, List

from src.agent.tools.registry import tool
from src.categories.index import list_templates, store as category_store
from src.common.logging import get_logger
from src.documents.builder import build_contract as build_contract_document
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
    name="build_contract",
    description="Формує фінальний договір у форматі DOCX на основі вже збережених полів.",
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
def build_contract_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    session_id = args["session_id"]
    template_id = args["template_id"]
    logger.info(
        "tool=build_contract session_id=%s template_id=%s", session_id, template_id
    )
    result = build_contract_document(session_id=session_id, template_id=template_id)
    session = load_session(session_id)
    session.state = SessionState.BUILT
    save_session(session)
    return result
