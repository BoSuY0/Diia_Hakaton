from typing import Any, Dict, Optional

from src.agent.tools.registry import tool
from src.categories.index import list_entities, list_party_fields
from src.common.logging import get_logger
from src.sessions.models import FieldState, SessionState
from src.sessions.store import load_session, save_session
from src.validators.core import validate_value

logger = get_logger(__name__)


def _unmask_value(value: str, tags: Dict[str, str] | None) -> str:
    if not tags:
        return value
    result = value
    for tag, raw in tags.items():
        if tag in result:
            result = result.replace(tag, raw)
    return result


def _recalculate_session_state(session) -> None:
    if not session.category_id:
        session.can_build_contract = False
        session.state = SessionState.IDLE
        return

    entities = list_entities(session.category_id)
    required_fields = [e.field for e in entities if e.required]

    all_ok = True
    for field_name in required_fields:
        fs = session.contract_fields.get(field_name)
        if fs is None or fs.status != "ok":
            all_ok = False
            break

    session.can_build_contract = all_ok

    progress = session.progress or {}
    progress["required_contract_fields_total"] = len(required_fields)
    progress["required_contract_fields_ok"] = sum(
        1
        for field_name in required_fields
        if (session.contract_fields.get(field_name) or FieldState()).status == "ok"
    )
    if all_ok:
        session.state = SessionState.READY_TO_BUILD
    else:
        session.state = SessionState.COLLECTING_FIELDS
        
    total_party = 0
    ok_party = 0
    if session.party_fields:
        for role_fields in session.party_fields.values():
            if isinstance(role_fields, dict):
                total_party += len(role_fields)
                ok_party += sum(1 for fs in role_fields.values() if fs.status == "ok")
    
    progress["required_party_fields_total"] = total_party
    progress["required_party_fields_ok"] = ok_party


@tool(
    name="upsert_field",
    description=(
        "Оновлює значення окремого поля в сесії (валідація + статуси). "
        "Очікується, що значення може містити PII-теги виду [TYPE#N], які буде розкрито на бекенді."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "minLength": 1,
            },
            "field": {
                "type": "string",
                "minLength": 1,
            },
            "value": {
                "type": "string",
                "minLength": 1,
            },
            "role": {
                "type": "string",
                "description": "Роль сторони (lessor, lessee тощо). Якщо вказано, поле буде збережено для цієї ролі.",
            },
        },
        "required": ["session_id", "field", "value"],
        "additionalProperties": False,
    }
)
def upsert_field_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    session_id = args["session_id"]
    field = args["field"]
    value = args["value"]
    role_arg = args.get("role")  # Optional role parameter
    tags = context.get("tags")

    session = load_session(session_id)
    if not session.category_id:
        return {
            "ok": False,
            "error": "Спочатку потрібно обрати категорію (set_category).",
        }

    # LAZY INITIALIZATION: If role is provided but not initialized, set it up automatically
    if role_arg:
        if role_arg not in session.party_types:
            # Auto-initialize with default person_type
            logger.info(
                "tool=upsert_field lazy_init_party role=%s default_person_type=individual",
                role_arg
            )
            session.party_types[role_arg] = "individual"
            session.party_fields[role_arg] = {}
            
        # Use the provided role for this field
        target_role = role_arg
        target_person_type = session.party_types[role_arg]
    else:
        # Use session's current role (backward compatibility)
        target_role = session.role
        target_person_type = session.person_type

    entities = {e.field: e for e in list_entities(session.category_id)}
    entity = entities.get(field)
    is_party_field = False
    
    if entity is None:
        # Check if it's a party field
        if not target_person_type:
            return {
                "ok": False,
                "error": "Спочатку потрібно обрати тип особи (set_party_context).",
            }
        party_fields = {
            f.field: f
            for f in list_party_fields(session.category_id, target_person_type)
        }
        party_meta = party_fields.get(field)
        if party_meta is None:
            return {
                "ok": False,
                "error": "Поле не належить до обраної категорії.",
            }
        is_party_field = True

    raw_value = _unmask_value(value, tags)
    
    logger.info(
        "tool=upsert_field session_id=%s field=%s role=%s is_party=%s raw_value_length=%d",
        session_id,
        field,
        target_role,
        is_party_field,
        len(raw_value),
    )

    if entity is not None:
        value_type = entity.type
    elif is_party_field and party_meta:
        value_type = party_meta.type
    else:
        value_type = "text"
    normalized, error = validate_value(value_type, raw_value)

    if is_party_field:
        if not target_role:
            return {
                "ok": False,
                "error": "Спочатку потрібно обрати роль (set_party_context).",
            }
        if target_role not in session.party_fields:
            session.party_fields[target_role] = {}
        
        fs = session.party_fields[target_role].get(field) or FieldState()
    else:
        fs = session.contract_fields.get(field) or FieldState()
    
    if error:
        fs.status = "error"
        fs.error = error
        ok = False
    else:
        fs.status = "ok"
        fs.error = None
        ok = True

    if is_party_field:
        session.party_fields[target_role][field] = fs
    else:
        session.contract_fields[field] = fs

    # History logic
    all_data = session.all_data or {}
    key = field
    if is_party_field and target_role:
        key = f"{target_role}.{field}"

    entry = all_data.get(key) or {}
    history = entry.get("history") or []
    history.append(
        {
            "source": "chat" if tags is not None else "chat",
            "value": raw_value,
            "normalized": normalized if error is None else None,
            "valid": error is None,
        }
    )
    entry["current"] = normalized if error is None else entry.get("current")
    entry["validated"] = error is None
    entry["source"] = "chat"
    entry["history"] = history
    all_data[key] = entry
    session.all_data = all_data
    
    _recalculate_session_state(session)
    save_session(session)

    return {
        "ok": ok,
        "field": field,
        "status": fs.status,
        "error": fs.error,
        "can_build_contract": session.can_build_contract,
        "state": session.state.value,
    }

