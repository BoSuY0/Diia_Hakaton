from typing import Any, Dict, List

from src.agent.tools.registry import tool
from src.common.logging import get_logger
from src.common.vsc import vsc_summary
from src.sessions.store import load_session
from src.categories.index import list_entities, list_party_fields

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

    # Load all possible fields for the category/role to show missing ones
    all_contract_fields = {}
    if session.category_id:
        for e in list_entities(session.category_id):
            all_contract_fields[e.field] = e

    all_party_fields = {}
    if session.category_id and session.person_type:
        for f in list_party_fields(session.category_id, session.person_type):
            all_party_fields[f.field] = f
            
    # Build contract fields summary (merging session state with definition)
    contract_summary = {}
    for field_name, entity in all_contract_fields.items():
        fs = session.contract_fields.get(field_name)
        status = fs.status if fs else "empty"
        error = fs.error if fs else None
        contract_summary[field_name] = {"status": status, "error": error, "required": entity.required, "label": entity.label}

    # Build party fields summary
    party_summary = {}
    # We focus on the current role/person_type context
    current_role = session.role
    if current_role:
        role_fields_state = session.party_fields.get(current_role) or {}
        for field_name, field_def in all_party_fields.items():
            fs = role_fields_state.get(field_name)
            status = fs.status if fs else "empty"
            error = fs.error if fs else None
            party_summary[field_name] = {"status": status, "error": error, "required": field_def.required, "label": field_def.label}

    return {
        "session_id": session_id,
        "category_id": session.category_id,
        "template_id": session.template_id,
        "role": session.role,
        "person_type": session.person_type,
        "state": session.state.value,
        "can_build_contract": session.can_build_contract,
        "contract_fields": contract_summary,
        "party_fields": {current_role: party_summary} if current_role else {},
        "progress": session.progress,
    }
