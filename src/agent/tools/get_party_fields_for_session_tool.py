from typing import Any, Dict, List

from src.agent.tools.registry import tool
from src.categories.index import PartyField, list_party_fields
from src.sessions.store import load_session


@tool(
    name="get_party_fields_for_session",
    description=(
        "Повертає список полів для сторони договору (name, address, тощо) "
        "залежно від обраної ролі та типу особи в поточній сесії."
    ),
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
    }
)
def get_party_fields_for_session_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    session_id = args["session_id"]
    session = load_session(session_id)
    
    if not session.category_id:
        return {
            "ok": False,
            "error": "Спочатку потрібно обрати категорію договору.",
        }
    
    current_person_type = session.person_type
    if session.role and session.party_types and session.role in session.party_types:
        current_person_type = session.party_types[session.role]
        
    if not current_person_type:
            return {
            "ok": False,
            "error": "Спочатку потрібно обрати тип особи (individual/fop/company).",
        }

    fields: List[PartyField] = list_party_fields(
        session.category_id,
        current_person_type,
    )
    return {
        "ok": True,
        "session_id": session_id,
        "role": session.role,
        "person_type": session.person_type,
        "fields": [
            {
                "field": f.field,
                "label": f.label,
                "required": f.required,
            }
            for f in fields
        ],
    }
