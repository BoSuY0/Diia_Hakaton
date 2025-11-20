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
from src.common.enums import ContractRole, PersonType, FillingMode
from src.common.logging import get_logger
from src.documents.builder import build_contract as build_contract_document
from src.sessions.models import FieldState, SessionState
from src.sessions.store import load_session, transactional_session
from src.validators.core import validate_value
from src.services.fields import validate_session_readiness

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

        with transactional_session(session_id) as session:
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

            # Return specific values, session is auto-saved
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
                    "enum": [r.value for r in ContractRole],
                },
                "person_type": {
                    "type": "string",
                    "enum": [p.value for p in PersonType],
                },
            },
            "required": ["session_id", "role", "person_type"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        role = args["role"]
        person_type = args["person_type"]

        # Validation via Enum
        try:
            ContractRole(role)
        except ValueError:
             return {
                "ok": False,
                "error": f"Невідома роль. Допустимі: {', '.join([r.value for r in ContractRole])}",
            }

        try:
            PersonType(person_type)
        except ValueError:
             return {
                "ok": False,
                "error": f"Невідомий тип особи. Допустимі: {', '.join([p.value for p in PersonType])}",
            }

        with transactional_session(session_id) as session:
            session.role = role
            session.person_type = person_type

            # Save party type for this role
            if session.party_types is None:
                session.party_types = {}
            session.party_types[role] = person_type

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
        # Read-only, use load_session
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
                    "enum": [r.value for r in ContractRole],
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

        with transactional_session(session_id) as session:
            if not session.category_id:
                return {
                    "ok": False,
                    "error": "Спочатку потрібно обрати категорію (set_category).",
                }

            # Unmask first
            raw_value = self._unmask_value(value, tags)

            # Centralized validation for all field types
            from src.validators.core import validate_value
            from src.categories.index import list_entities, list_party_fields
            from src.sessions.models import FieldState

            entities = {e.field: e for e in list_entities(session.category_id)}
            entity = entities.get(field)
            is_party_field = False

            if entity is None:
                effective_role = target_role or session.role
                if not effective_role:
                     return {
                        "ok": False,
                        "error": "Спочатку потрібно обрати роль (set_party_context) або передати її явно.",
                    }

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
            else:
                # Contract field
                effective_role = None # Not needed for contract fields

            logger.info(
                "tool=upsert_field session_id=%s field=%s raw_value_length=%d role=%s",
                session_id,
                field,
                len(raw_value),
                target_role or "current",
            )

            value_type = "text"
            if entity:
                value_type = entity.type
            elif is_party_field:
                 # Heuristic mapping for party fields
                 if "rnokpp" in field or "tax_id" in field:
                     value_type = "rnokpp"
                 elif "edrpou" in field:
                     value_type = "edrpou"
                 elif "iban" in field:
                     value_type = "iban"
                 elif "date" in field:
                     value_type = "date"
                 elif "email" in field:
                     value_type = "email"

            normalized, error = validate_value(value_type, raw_value)

            if is_party_field:
                if not effective_role:
                     return {
                        "ok": False,
                        "error": "Role not determined.",
                    }

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

            # Recalculate state using shared service
            is_ready = validate_session_readiness(session)
            session.can_build_contract = is_ready
            if is_ready:
                session.state = SessionState.READY_TO_BUILD
            else:
                session.state = SessionState.COLLECTING_FIELDS

            # Update progress (rough estimate for info)
            # We could use get_required_fields to get exact count, but let's leave as is for now or update?
            # Updating progress logic is good.
            from src.services.fields import get_required_fields
            required = get_required_fields(session)

            total_req = len(required)
            filled_req = 0
            for r in required:
                if r.role:
                    rf = session.party_fields.get(r.role) or {}
                    st = rf.get(r.field_name)
                    if st and st.status == "ok":
                        filled_req += 1
                else:
                    st = session.contract_fields.get(r.field_name)
                    if st and st.status == "ok":
                        filled_req += 1

            progress = session.progress or {}
            progress["required_total"] = total_req
            progress["required_filled"] = filled_req
            session.progress = progress

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
        # Read-only
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
                    "enum": [m.value for m in FillingMode],
                },
            },
            "required": ["session_id", "mode"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        mode = args["mode"]

        with transactional_session(session_id) as session:
            session.filling_mode = mode
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
        # Build contract is READ ONLY operation on session data usually,
        # but it updates session state to BUILT.
        # build_contract_document might fail if we lock session inside it using load_session?
        # Let's check builder.py. It calls load_session.
        # If we wrap this call in transactional_session, and build_contract calls load_session (no lock), it works (reentrancy is fine for read vs write lock? No, load_session has NO lock).
        # But we want to update session state.

        # Ideally:
        # 1. Build document (read session)
        # 2. Update session state (write session)

        # If build_contract_document takes long time, holding lock is bad?
        # But we need consistency.

        # Let's look at builder.py.

        result = build_contract_document(session_id=session_id, template_id=template_id)

        with transactional_session(session_id) as session:
            session.state = SessionState.BUILT

        return result
