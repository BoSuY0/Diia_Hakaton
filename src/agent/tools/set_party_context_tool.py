from typing import Any, Dict

from src.agent.tools.registry import tool
from src.categories.index import get_role_info, get_roles
from src.sessions.store import load_session, save_session


@tool(
    name="set_party_context",
    description=(
        "Встановлює роль користувача в договорі та тип особи для поточної сесії. "
        "Ролі та типи визначаються метаданими категорії."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "minLength": 1,
            },
            "role": {
                "type": "string",
                "description": "Роль у договорі (lessor, lessee, seller, buyer, тощо)",
            },
            "person_type": {
                "type": "string",
                "description": "Тип особи (individual, fop, company)",
            },
        },
        "required": ["session_id", "role", "person_type"],
        "additionalProperties": False,
    }
)
def set_party_context_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    session_id = args["session_id"]
    role = args["role"]
    person_type = args["person_type"]
    
    session = load_session(session_id)

    if not session.category_id:
        return {
            "ok": False,
            "error": "Спочатку потрібно обрати категорію (set_category).",
        }

    # Dynamic validation of roles
    allowed_roles = get_roles(session.category_id)
    if role not in allowed_roles:
        return {
            "ok": False,
            "error": f"Невідома роль '{role}'. Допустимі ролі: {', '.join(allowed_roles)}",
        }
    
    # Dynamic validation of person types
    role_info = get_role_info(session.category_id, role)
    allowed_person_types = role_info.get("allowed_person_types", [])
    if person_type not in allowed_person_types:
        return {
            "ok": False,
            "error": f"Тип '{person_type}' не дозволений для ролі '{role}'. Допустимі типи: {', '.join(allowed_person_types)}",
        }

    session.role = role
    session.person_type = person_type
    
    # Save party type for this role
    if session.party_types is None:
        session.party_types = {}
    session.party_types[role] = person_type
    
    save_session(session)

    return {
        "ok": True,
        "role": role,
        "person_type": person_type,
    }
