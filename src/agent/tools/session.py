from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agent.tools.base import BaseTool
from src.agent.tools.registry import register_tool
from src.categories.index import (
    Entity,
    PartyField,
    list_entities,
    list_party_fields,
    list_templates,
)
from src.common.logging import get_logger
from src.documents.builder import build_contract as build_contract_document
from src.sessions.models import FieldState, SessionState
from src.sessions.store import load_session, save_session
from src.validators.core import validate_value

logger = get_logger(__name__)


def _template_ids() -> List[str]:
    # This helper might need to be more efficient or cached, 
    # but for now we replicate original logic
    from src.categories.index import store as category_store
    ids: set[str] = set()
    try:
        for category in category_store.categories.values():
            for t in list_templates(category.id):
                ids.add(t.id)
    except Exception:
        return []
    return sorted(ids)


@register_tool
class SetTemplateTool(BaseTool):
    @property
    def name(self) -> str:
        return "set_template"

    @property
    def description(self) -> str:
        return "Set contract template within category."

    @property
    def parameters(self) -> Dict[str, Any]:
        ids = _template_ids()
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "minLength": 1,
                },
                "template_id": (
                    {
                        "type": "string",
                        "enum": ids,
                    }
                    if ids
                    else {
                        "type": "string",
                        "minLength": 1,
                    }
                )
            },
            "required": ["session_id", "template_id"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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
        if template_id not in templates:
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


@register_tool
class SetPartyContextTool(BaseTool):
    @property
    def name(self) -> str:
        return "set_party_context"

    @property
    def description(self) -> str:
        return "Set user role (lessor/lessee) and person type (individual/fop/company)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "minLength": 1,
                },
                "role": {
                    "type": "string",
                    "enum": ["lessor", "lessee"],
                },
                "person_type": {
                    "type": "string",
                    "enum": ["individual", "fop", "company"],
                },
            },
            "required": ["session_id", "role", "person_type"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        role = args["role"]
        person_type = args["person_type"]
        
        session = load_session(session_id)

        allowed_roles = {"lessor", "lessee"}
        allowed_person_types = {"individual", "fop", "company"}

        if role not in allowed_roles:
            return {
                "ok": False,
                "error": "Невідома роль у договорі (очікується lessor/lessee).",
            }
        if person_type not in allowed_person_types:
            return {
                "ok": False,
                "error": "Невідомий тип особи (очікується individual/fop/company).",
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


@register_tool
class GetPartyFieldsForSessionTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_party_fields_for_session"

    @property
    def description(self) -> str:
        return "Get party fields (name, address, etc) for current role/type."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
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

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        session = load_session(session_id)
        
        if not session.category_id:
            return {
                "ok": False,
                "error": "Спочатку потрібно обрати категорію договору.",
            }
        # Determine person type for the current role
        # Fallback to session.person_type if not in party_types (backward compat)
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


@register_tool
class UpsertFieldTool(BaseTool):
    @property
    def name(self) -> str:
        return "upsert_field"

    @property
    def description(self) -> str:
        return "Update field value. Handles PII tags [TYPE#N] automatically."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "minLength": 1,
                },
                "role": {
                    "type": "string",
                    "enum": ["lessor", "lessee"],
                    "description": "Optional. Explicitly specify which party this field belongs to. If not provided, uses the current session role.",
                },
                "field": {
                    "type": "string",
                    "minLength": 1,
                },
                "value": {
                    "type": "string",
                    "minLength": 1,
                },
            },
            "required": ["session_id", "field", "value"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        field = args["field"]
        value = args["value"]
        # Allow explicit role override, otherwise fallback to session active role
        target_role = args.get("role")
        tags = context.get("tags") # Tags passed via context

        session = load_session(session_id)
        if not session.category_id:
            return {
                "ok": False,
                "error": "Спочатку потрібно обрати категорію (set_category).",
            }

        # Logic copied from original tool_upsert_field
        entities = {e.field: e for e in list_entities(session.category_id)}
        entity = entities.get(field)
        is_party_field = False
        
        if entity is None:
            # If target_role is not provided, we need session.person_type
            # If target_role IS provided, we need to know the person_type for THAT role.
            
            effective_role = target_role or session.role
            if not effective_role:
                 return {
                    "ok": False,
                    "error": "Спочатку потрібно обрати роль (set_party_context) або передати її явно.",
                }
            
            # Determine person type for the effective role
            effective_person_type = None
            if session.party_types and effective_role in session.party_types:
                effective_person_type = session.party_types[effective_role]
            elif effective_role == session.role:
                effective_person_type = session.person_type
            
            if not effective_person_type:
                return {
                    "ok": False,
                    "error": f"Невідомий тип особи для ролі {effective_role}. Встановіть контекст або тип особи.",
                }

            party_fields = {
                f.field: f
                for f in list_party_fields(session.category_id, effective_person_type)
            }
            party_meta = party_fields.get(field)
            if party_meta is None:
                return {
                    "ok": False,
                    "error": "Поле не належить до обраної категорії.",
                }
            is_party_field = True

        # Unmask
        raw_value = self._unmask_value(value, tags)
        
        logger.info(
            "tool=upsert_field session_id=%s field=%s raw_value_length=%d role=%s",
            session_id,
            field,
            len(raw_value),
            target_role or "current",
        )

        value_type = entity.type if entity is not None else "text"
        normalized, error = validate_value(value_type, raw_value)

        if is_party_field:
            # Use effective_role determined above
            if not effective_role:
                 return {
                    "ok": False,
                    "error": "Role not determined.",
                }
            
            # Ensure role dict exists
            if effective_role not in session.party_fields:
                session.party_fields[effective_role] = {}
            
            fs = session.party_fields[effective_role].get(field) or FieldState()
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
            session.party_fields[effective_role][field] = fs
        else:
            session.contract_fields[field] = fs

        # History logic
        all_data = session.all_data or {}
        key = field
        if is_party_field and effective_role:
            key = f"{effective_role}.{field}"

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
        
        self._recalculate_session_state(session)
        save_session(session)

        return {
            "ok": ok,
            "field": field,
            "status": fs.status,
            "error": fs.error,
            "can_build_contract": session.can_build_contract,
            "state": session.state.value,
        }

    def _unmask_value(self, value: str, tags: Dict[str, str] | None) -> str:
        if not tags:
            return value
        result = value
        for tag, raw in tags.items():
            if tag in result:
                result = result.replace(tag, raw)
        return result

    def _recalculate_session_state(self, session) -> None:
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
        
        # Check party fields if contract fields are ok
        if all_ok:
            from src.categories.index import list_party_fields, store as cat_store, _load_meta
            category_def = cat_store.get(session.category_id)
            if category_def:
                meta = _load_meta(category_def)
                roles = meta.get("roles") or {}
                for role_key in roles.keys():
                    p_type = session.party_types.get(role_key)
                    if not p_type:
                         if session.role == role_key and session.person_type:
                             p_type = session.person_type
                         else:
                             p_type = "individual"
                    
                    party_fields_list = list_party_fields(session.category_id, p_type)
                    for pf in party_fields_list:
                        if pf.required:
                            role_fields = session.party_fields.get(role_key) or {}
                            fs = role_fields.get(pf.field)
                            if not fs or fs.status != "ok":
                                all_ok = False
                                break
                    if not all_ok:
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
            
        # Calculate party fields progress (optional, for info)
        total_party = 0
        ok_party = 0
        if session.party_fields:
            for role_fields in session.party_fields.values():
                if isinstance(role_fields, dict):
                    total_party += len(role_fields)
                    ok_party += sum(1 for fs in role_fields.values() if fs.status == "ok")
        
        progress["required_party_fields_total"] = total_party # This is just filled count, not required count
        progress["required_party_fields_ok"] = ok_party


@register_tool
class GetSessionSummaryTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_session_summary"

    @property
    def description(self) -> str:
        return "Get session field status summary (no values)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
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

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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

    def format_result(self, result: Any) -> str:
        from src.common.vsc import vsc_summary
        return vsc_summary(result)


@register_tool
class SetFillingModeTool(BaseTool):
    @property
    def name(self) -> str:
        return "set_filling_mode"

    @property
    def description(self) -> str:
        return "Set filling mode: 'partial' (one side) or 'full' (both sides)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "minLength": 1,
                },
                "mode": {
                    "type": "string",
                    "enum": ["partial", "full"],
                },
            },
            "required": ["session_id", "mode"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        mode = args["mode"]
        
        session = load_session(session_id)
        session.filling_mode = mode
        save_session(session)

        return {
            "ok": True,
            "filling_mode": mode,
        }

@register_tool
class BuildContractTool(BaseTool):
    @property
    def name(self) -> str:
        return "build_contract"

    @property
    def description(self) -> str:
        return "Generate final DOCX contract."

    @property
    def parameters(self) -> Dict[str, Any]:
        ids = _template_ids()
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "minLength": 1,
                },
                "template_id": (
                    {
                        "type": "string",
                        "enum": ids,
                    }
                    if ids
                    else {
                        "type": "string",
                        "minLength": 1,
                    }
                )
            },
            "required": ["session_id", "template_id"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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
