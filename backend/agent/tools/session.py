"""Session management tools for the AI agent."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.agent.tools.base import BaseTool
from backend.agent.tools.registry import register_tool
from backend.agent.tools.schema_helpers import (
    string_enum_or_minlength,
    base_session_parameters,
)
from backend.domain.categories.index import (
    PartyField,
    list_entities,
    list_party_fields,
    list_templates,
    store as category_store,
    load_meta,
)
from backend.domain.documents.builder import build_contract as build_contract_document
from backend.domain.services.session import (
    can_edit_contract_field,
    can_edit_party_field,
    get_effective_person_type,
)
from backend.domain.sessions.models import SessionState
from backend.infra.persistence.store import (
    aload_session,
    atransactional_session,
)
from backend.shared.enums import PersonType, FillingMode
from backend.shared.errors import SessionNotFoundError
from backend.shared.logging import get_logger

logger = get_logger(__name__)


def _get_main_role(category_id: str | None) -> str | None:
    """
    UI helper to pick the first role from metadata order.
    """
    if not category_id:
        return None
    try:
        cat = category_store.get(category_id)
        if not cat:
            return None
        meta = load_meta(cat)
        roles = meta.get("roles") or {}
        for role_key in roles.keys():
            return role_key
    except (FileNotFoundError, KeyError, TypeError):
        return None
    return None


def _template_ids() -> List[str]:
    """Get all template IDs from all categories."""
    ids: set[str] = set()
    try:
        for category in category_store.categories.values():
            for t in list_templates(category.id):
                ids.add(t.id)
    except (AttributeError, TypeError):
        return []
    return sorted(ids)


@register_tool
class SetTemplateTool(BaseTool):
    """Tool to set contract template within a category."""

    @property
    def name(self) -> str:
        return "set_template"

    @property
    def description(self) -> str:
        return "Set contract template within category."

    @property
    def parameters(self) -> Dict[str, Any]:
        return base_session_parameters(
            extra_properties={"template_id": string_enum_or_minlength(_template_ids())},
            extra_required=["template_id"],
        )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        template_id = args["template_id"]

        async with atransactional_session(session_id) as session:
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

            from backend.domain.services.session import set_session_template  # pylint: disable=import-outside-toplevel
            set_session_template(session, template_id)

            return {
                "ok": True,
                "category_id": session.category_id,
                "template_id": template_id,
            }


@register_tool
class SetPartyContextTool(BaseTool):
    """Tool to set user role and person type for a session."""

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
                "filling_mode": {
                    "type": "string",
                    "enum": [m.value for m in FillingMode],
                    "description": "Optional filling mode override.",
                }
            },
            "required": ["session_id", "role", "person_type"],
            "additionalProperties": False,
        }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        role = args["role"]
        person_type = args["person_type"]
        filling_mode = args.get("filling_mode")

        try:
            PersonType(person_type)
        except ValueError:
            return {
                "ok": False,
                "error": f"Невідомий тип особи. Допустимі: "
                         f"{', '.join([p.value for p in PersonType])}",
            }

        # Validate person_type against category metadata
        user_id = context.get("user_id") or args.get("user_id")
        if not user_id:
            return {"ok": False, "error": "Необхідний заголовок X-User-ID.", "status_code": 401}

        # Ensure category metadata is available (reload if needed)
        if category_store.categories is None or not category_store.categories:
            try:
                category_store.load()
            except (FileNotFoundError, OSError) as exc:
                logger.error("set_party_context: failed to load categories: %s", exc)
                return {"ok": False, "error": "Не вдалося завантажити метадані категорій."}

        try:
            async with atransactional_session(session_id) as session:
                if not session.category_id:
                    return {"ok": False, "error": "Спочатку оберіть категорію.", "status_code": 400}

                cat = category_store.get(session.category_id)
                if not cat:
                    return {
                        "ok": False,
                        "error": f"Невідома категорія: {session.category_id}.",
                        "status_code": 404,
                    }

                try:
                    meta = load_meta(cat)
                except FileNotFoundError:
                    return {"ok": False, "error": "Метадані категорії відсутні."}
                except (OSError, KeyError) as exc:
                    logger.error(
                        "set_party_context: failed to read meta for %s: %s",
                        session.category_id, exc,
                    )
                    return {"ok": False, "error": "Не вдалося прочитати метадані категорії."}

                roles_meta = (meta.get("roles") or {})
                role_meta = roles_meta.get(role)
                if not role_meta:
                    return {
                        "ok": False,
                        "error": "Невідома роль для цієї категорії.",
                        "status_code": 400,
                    }

                allowed_types = role_meta.get("allowed_person_types", []) if role_meta else []
                if allowed_types and person_type not in allowed_types:
                    return {
                        "ok": False,
                        "error": "Невірний тип особи для ролі.",
                        "status_code": 400,
                    }

                from backend.domain.services.session import (  # pylint: disable=import-outside-toplevel
                    set_party_type, claim_session_role,
                )
                
                # Determine if we need to claim the role or just set person_type
                current_owner = (session.role_owners or {}).get(role)
                is_full_mode = session.filling_mode == "full"
                is_creator = session.creator_user_id == user_id
                
                # Перевіряємо чи користувач вже володіє іншою роллю
                user_existing_role = next(
                    (r for r, uid in (session.role_owners or {}).items() if uid == user_id),
                    None
                )
                
                if current_owner == user_id:
                    # User already owns this role - just update person_type
                    pass
                elif current_owner and current_owner != user_id:
                    # Role is owned by someone else - deny
                    return {
                        "ok": False,
                        "error": f"Роль '{role}' вже зайнята іншим користувачем.",
                        "status_code": 403,
                    }
                elif user_existing_role and user_existing_role != role:
                    # В режимі full - творець може редагувати дані інших ролей БЕЗ їх закріплення
                    # Він вже володіє своєю роллю, а дані для інших - тільки заповнює
                    if is_full_mode and is_creator:
                        # Дозволяємо встановити person_type для іншої ролі без закріплення
                        # Ця роль буде доступна для приєднання іншого користувача
                        pass
                    else:
                        # В режимі partial - користувач не може редагувати інші ролі
                        return {
                            "ok": False,
                            "error": f"Ви вже обрали роль '{user_existing_role}'. В режимі 'partial' можна редагувати лише свою роль.",
                            "status_code": 403,
                        }
                else:
                    # Need to claim the role - це перша роль користувача
                    try:
                        claim_session_role(session, role, user_id)
                    except PermissionError as exc:
                        return {"ok": False, "error": str(exc), "status_code": 403}
                    except ValueError as exc:
                        return {"ok": False, "error": str(exc), "status_code": 400}

                # Set person type
                set_party_type(session, role, person_type)

                if filling_mode:
                    try:
                        session.filling_mode = FillingMode(filling_mode).value
                    except ValueError:
                        session.filling_mode = filling_mode

                return {
                    "ok": True,
                    "role": role,
                    "person_type": person_type,
                    "user_id": user_id,
                    "filling_mode": session.filling_mode,
                }
        except SessionNotFoundError:
            return {
                "ok": False,
                "error": "Сесію не знайдено або вона недоступна.",
                "status_code": 404,
            }


@register_tool
class GetPartyFieldsForSessionTool(BaseTool):
    """Tool to get party fields for the current session role/type."""

    @property
    def name(self) -> str:
        return "get_party_fields_for_session"

    @property
    def description(self) -> str:
        return "Get party fields (name, address, etc) for current role/type."

    @property
    def parameters(self) -> Dict[str, Any]:
        return base_session_parameters()

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        # Read-only, use load_session
        session = await aload_session(session_id)

        if not session.category_id:
            return {
                "ok": False,
                "error": "Спочатку потрібно обрати категорію договору.",
            }
        # Use centralized function for determining person type
        current_person_type = None
        if session.role:
            current_person_type = get_effective_person_type(
                session, session.role, apply_fallback=False
            )

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
                meta = json.loads(cat.meta_path.read_text(encoding="utf-8"))
                role_label = meta.get("roles", {}).get(session.role, {}).get("label")
                person_type_label = (
                    meta.get("party_modules", {})
                    .get(current_person_type, {})
                    .get("label")
                )
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
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
    """Tool to update a field value in a session."""

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
                    "description": "Optional. Party this field belongs to.",
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
    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
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

        async with atransactional_session(session_id) as session:
            # Access Control Check
            user_id = context.get("user_id") or args.get("user_id")

            if not user_id:
                return {"ok": False, "error": "Необхідний заголовок X-User-ID."}

            if session.category_id:
                entities = {e.field: e for e in list_entities(session.category_id)}
            else:
                entities = {}
            entity = entities.get(field)

            # Доступ до умов договору (contract fields)
            if entity is not None:
                if not can_edit_contract_field(session, acting_user_id=user_id, field_name=field):
                    return {
                        "ok": False,
                        "error": "Вам не дозволено редагувати це поле договору.",
                        "status_code": 403,
                    }
            elif session.category_id:
                # It is a party field
                effective_role = role_arg or session.role
                if effective_role:
                    can_edit = can_edit_party_field(
                        session, acting_user_id=user_id, target_role=effective_role
                    )
                    if not can_edit:
                        return {
                            "ok": False,
                            "error": f"Ви не маєте права редагувати поля ролі '{effective_role}'.",
                            "status_code": 403,
                        }

            from backend.domain.services.session import update_session_field  # pylint: disable=import-outside-toplevel

            ok, error, fs = update_session_field(
                session=session,
                field=field,
                value=real_value,
                role=role_arg,
                tags=tags, # Pass tags for history tracking
                context={**context, "user_id": user_id},
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
    """Tool to get session field status summary."""

    @property
    def name(self) -> str:
        return "get_session_summary"

    @property
    def description(self) -> str:
        return "Get session field status summary (no values)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return base_session_parameters()

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        # Read-only
        session = await aload_session(session_id)
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
            "role_owners": session.role_owners,
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
        from backend.shared.vsc import vsc_summary  # pylint: disable=import-outside-toplevel
        return vsc_summary(result)


@register_tool
class SetFillingModeTool(BaseTool):
    """Tool to set the filling mode for a session."""

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

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        mode = args["mode"]
        user_id = context.get("user_id")

        async with atransactional_session(session_id) as session:
            # Access check
            if session.role_owners:
                if not user_id:
                    return {"ok": False, "error": "Необхідна авторизація для зміни режиму."}
                if user_id not in session.role_owners.values():
                    return {"ok": False, "error": "Ви не є учасником цієї сесії."}

            session.filling_mode = mode
            return {
                "ok": True,
                "filling_mode": mode,
            }


@register_tool
class BuildContractTool(BaseTool):
    """Tool to generate the final DOCX contract."""

    @property
    def name(self) -> str:
        return "build_contract"

    @property
    def description(self) -> str:
        return "Generate final DOCX contract."

    @property
    def parameters(self) -> Dict[str, Any]:
        return base_session_parameters(
            extra_properties={"template_id": string_enum_or_minlength(_template_ids())},
            extra_required=["template_id"],
        )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        template_id = args["template_id"]
        logger.info(
            "tool=build_contract session_id=%s template_id=%s", session_id, template_id
        )
        # build_contract_document is async; call it directly
        result = await build_contract_document(
            session_id=session_id, template_id=template_id
        )

        async with atransactional_session(session_id) as session:
            session.state = SessionState.BUILT

        return result


@register_tool
class SignContractTool(BaseTool):
    """Tool to sign the contract for a specific role."""

    @property
    def name(self) -> str:
        return "sign_contract"

    @property
    def description(self) -> str:
        return "Sign the contract for the current role."

    @property
    def parameters(self) -> Dict[str, Any]:
        return base_session_parameters(
            extra_properties={
                "role": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Role to sign as.",
                }
            },
        )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        session_id = args["session_id"]
        role_arg = args.get("role")
        user_id = context.get("user_id")

        async with atransactional_session(session_id) as session:
            # Determine role
            role = role_arg or session.role
            if not role:
                return {
                    "ok": False,
                    "error": "Не визначена роль для підпису. "
                           "Встановіть контекст або передайте роль.",
                }

            # Check state
            if session.state not in [SessionState.BUILT, SessionState.READY_TO_SIGN]:
                return {
                    "ok": False,
                    "error": f"Не можна підписати договір у стані "
                           f"{session.state.value}. Спочатку сформуйте його.",
                }

            if not user_id:
                return {"ok": False, "error": "Необхідний X-User-ID для підпису."}

            owner = session.role_owners.get(role)
            if not owner:
                return {"ok": False, "error": "Спочатку прив'яжіть роль через set_party_context."}
            if owner != user_id:
                return {"ok": False, "error": "Ви не маєте права підписувати за цю роль."}

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

            session.history.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "type": "sign",
                    "user_id": user_id,
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
