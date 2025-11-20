from typing import Any, Dict, List

from src.agent.tools.registry import tool
from src.common.logging import get_logger
from src.common.vsc import vsc_summary
from src.sessions.store import load_session

logger = get_logger(__name__)


@tool(
    name="get_session_summary",
    description="Повертає статус заповнення полів для сесії (без значень).",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "minLength": 1,
            }
        },
        "required": ["session_id"],
        "additionalProperties": False,
    },
    format_result_func=vsc_summary
)
def get_session_summary_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    session_id = args["session_id"]
    session = load_session(session_id)
    logger.info(
        "tool=get_session_summary session_id=%s category_id=%s template_id=%s state=%s",
        session_id,
        session.category_id,
        session.template_id,
        session.state.value,
    )

    fields_summary: List[Dict[str, Any]] = []
    for field_name, fs in session.contract_fields.items():
        fields_summary.append(
            {
                "field": field_name,
                "filled": fs.status == "ok",
                "status": fs.status,
                "error": fs.error,
            }
        )

    return {
        "session_id": session_id,
        "category_id": session.category_id,
        "template_id": session.template_id,
        "state": session.state.value,
        "can_build_contract": session.can_build_contract,
        "fields": fields_summary,
        "party_fields": {
            role: {
                name: {"status": fs.status, "error": fs.error}
                for name, fs in fields.items()
            }
            for role, fields in session.party_fields.items()
        },
        "contract_fields": {
            name: {"status": fs.status, "error": fs.error}
            for name, fs in session.contract_fields.items()
        },
        "progress": session.progress,
    }
