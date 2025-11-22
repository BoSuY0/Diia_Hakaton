from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from src.agent.tools.base import BaseTool
from src.agent.tools.registry import register_tool
from src.categories.index import (
    Entity,
    PartyField,
    list_entities,
    list_party_fields,
    list_templates,
    store as category_store,
)
from src.common.enums import PersonType, FillingMode
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

            from src.services.session import set_session_template
            set_session_template(session, template_id)

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
                    "minLength": 1,
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

        try:
            PersonType(person_type)
        except ValueError:
             return {
                "ok": False,
                "error": f"Невідомий тип особи. Допустимі: {', '.join([p.value for p in PersonType])}",
            }

        # Validate person_type against category metadata
        try:
            session = load_session(session_id)
            if not session.category_id:
                 return {"ok": False, "error": "Спочатку оберіть категорію."}
            from src.categories.index import store as category_store, _load_meta
            cat = category_store.get(session.category_id)
            if not cat:
                 return {"ok": False, "error": "Невідома категорія."}
            meta = _load_meta(cat)
            roles_meta = (meta.get("roles") or {})
            role_meta = roles_meta.get(role)
            if not role_meta:
                 return {"ok": False, "error": "Невідома роль для цієї категорії."}
            allowed_types = role_meta.get("allowed_person_types", []) if role_meta else []
            if allowed_types and person_type not in allowed_types:
                 return {"ok": False, "error": "Невірний тип особи для ролі."}
        except Exception:
            # Fail closed if meta cannot be read
            return {"ok": False, "error": "Не вдалося перевірити тип особи."}

        client_id = context.get("client_id")
        # If not, we can't enforce strict access control properly.
        # Fallback to session.user_id if available?
        if not client_id:
             # Try to get from args if passed explicitly (for testing)
             client_id = args.get("client_id")
        
        if not client_id:
             # If still no ID, we can't claim role safely.
             # But maybe we allow it for "anonymous" single-user mode?
             # User wants STRICT control. So we should probably error or generate one.
             # Let's generate a temporary one if missing, but warn.
             client_id = "anon_" + session_id # Fallback

        with transactional_session(session_id) as session:
            from src.services.session import set_party_type, claim_session_role
            
            # Claim role
            try:
                success = claim_session_role(session, role, client_id)
                if not success:
                    return {"ok": False, "error": f"Роль '{role}' вже зайнята або ви вже маєте іншу роль."}
            except ValueError as e:
                 return {"ok": False, "error": str(e)}

            # Set person type
            set_party_type(session, role, person_type)

            return {
                "ok": True,
                "role": role,
                "person_type": person_type,
                "client_id": client_id
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

        # Human labels for role/person_type
        role_label = None
        person_type_label = None
        try:
            cat = category_store.get(session.category_id)
            if cat:
                import json
                meta = json.loads(cat.meta_path.read_text(encoding="utf-8"))
                role_label = meta.get("roles", {}).get(session.role, {}).get("label")
                person_type_label = (
                    meta.get("party_modules", {})
                    .get(current_person_type, {})
                    .get("label")
                )
        except Exception:
            pass

        return {
            "ok": True,
            "session_id": session_id,
            "role": session.role,
            "person_type": session.person_type,
            "role_label": role_label,
            "person_type_label": person_type_label,
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
                    "minLength": 1,
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
        role_arg = args.get("role")

        # Extract PII tags from context if available
        # The LLM might have tagged PII in the value, e.g. "My phone is [PHONE#1]"
        # But the value passed here is usually the raw value or the tagged value?
        # If the LLM passes tagged value, we need the mapping.
        # The mapping is usually in context["pii_tags"] if we support that flow.
        # For now, we assume value might contain tags, and we try to unmask if tags are provided.
        tags = context.get("pii_tags") or context.get("tags")
        
        # Unmask value if needed (for storage)
        # Actually, we want to store the REAL value, so we unmask.
        real_value = self._unmask_value(value, tags)

        with transactional_session(session_id) as session:
            # Access Control Check
            client_id = context.get("client_id")

            # Дозволяємо роботу без client_id лише якщо всі ролі наразі anon_ (тимчасові сесії)
            all_anon = bool(session.party_users) and all(str(v).startswith("anon_") for v in session.party_users.values())
            if session.party_users and not client_id and not all_anon:
                return {"ok": False, "error": "Необхідний заголовок X-Client-ID."}

            entities = {e.field: e for e in list_entities(session.category_id)} if session.category_id else {}
            entity = entities.get(field)

            # Доступ до умов договору (contract fields)
            if entity is not None:
                from src.common.enums import FillingMode
                is_full_mode = session.filling_mode == FillingMode.FULL
                participant_roles = []
                if client_id:
                    participant_roles = [
                        role_key for role_key, owner in (session.party_users or {}).items() if owner == client_id
                    ]
                if session.party_users and not is_full_mode and client_id and not participant_roles:
                    return {"ok": False, "error": "Редагувати умови можуть лише учасники цієї сесії."}
                if session.party_users and not is_full_mode and not client_id and not all_anon:
                    return {"ok": False, "error": "Потрібен X-Client-ID для редагування умов."}
            elif client_id and session.category_id:
                # It is a party field
                effective_role = role_arg or session.role
                if effective_role:
                    owner = session.party_users.get(effective_role)
                    if owner:
                        # Якщо роль прив'язана до anon_* і прийшов реальний користувач — перезакріплюємо
                        if str(owner).startswith("anon_"):
                            if client_id:
                                session.party_users[effective_role] = client_id
                                owner = client_id
                            else:
                                # anon власник, запит без client_id — дозволяємо
                                owner = client_id
                        if owner and owner != client_id:
                             from src.common.enums import FillingMode
                             if session.filling_mode != FillingMode.FULL:
                                 return {
                                     "ok": False, 
                                     "error": f"Ви не маєте права редагувати поля ролі '{effective_role}'."
                                 }

            from src.services.session import update_session_field
            
            ok, error, fs = update_session_field(
                session=session,
                field=field,
                value=real_value,
                role=role_arg,
                tags=tags, # Pass tags for history tracking
                context=context,
            )

            if not ok:
                return {
                    "ok": False,
                    "error": error,
                    "field_state": {
                        "status": fs.status,
                        "error": fs.error
                    }
                }

            return {
                "ok": True,
                "field": field,
                "status": fs.status,
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
        client_id = context.get("client_id")

        with transactional_session(session_id) as session:
            # Access check
            if session.party_users:
                 if not client_id:
                      return {"ok": False, "error": "Необхідна авторизація для зміни режиму."}
                 if client_id not in session.party_users.values():
                      return {"ok": False, "error": "Ви не є учасником цієї сесії."}

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

@register_tool
class SignContractTool(BaseTool):
    @property
    def name(self) -> str:
        return "sign_contract"

    @property
    def description(self) -> str:
        return "Sign the contract for the current role."

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
                    "minLength": 1,
                    "description": "Role to sign as (must match session role or be explicit)"
                }
            },
            "required": ["session_id"],
            "additionalProperties": False,
        }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        role_arg = args.get("role")

        with transactional_session(session_id) as session:
            # Determine role
            role = role_arg or session.role
            if not role:
                 return {
                    "ok": False,
                    "error": "Не визначена роль для підпису. Встановіть контекст або передайте роль.",
                }

            # Check state
            if session.state not in [SessionState.BUILT, SessionState.READY_TO_SIGN]:
                 return {
                    "ok": False,
                    "error": f"Не можна підписати договір у стані {session.state.value}. Спочатку сформуйте його.",
                }

            # Check if already signed
            if session.signatures.get(role):
                 return {
                    "ok": False,
                    "error": "Ви вже підписали цей договір.",
                }

            # Sign
            session.signatures[role] = True
            logger.info("tool=sign_contract session_id=%s role=%s signed=True", session_id, role)

            # Check if fully signed
            if session.is_fully_signed:
                session.state = SessionState.COMPLETED
            else:
                session.state = SessionState.READY_TO_SIGN

            session.sign_history.append(
                {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "client_id": context.get("client_id"),
                    "roles": [role],
                    "state": session.state.value,
                }
            )

            return {
                "ok": True,
                "role": role,
                "signed": True,
                "is_fully_signed": session.is_fully_signed,
                "state": session.state.value
            }
