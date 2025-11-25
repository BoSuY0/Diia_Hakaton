"""Session management service functions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from backend.domain.categories.index import (
    list_entities,
    list_party_fields,
    load_meta,
    store as category_store,
)
from backend.domain.services.fields import (
    get_required_fields,
    validate_session_readiness,
)
from backend.domain.sessions.models import FieldState, Session, SessionState
from backend.domain.validation.core import infer_value_type, validate_value
from backend.shared.enums import FillingMode
from backend.shared.logging import get_logger

logger = get_logger(__name__)


def get_effective_person_type(
    session: Session,
    role: str,
    *,
    apply_fallback: bool = True,
) -> Optional[str]:
    """Get the effective person type for a role in the session.

    This centralizes the logic for determining person_type to avoid
    inconsistent fallback behavior across different parts of the codebase.

    Args:
        session: The session object.
        role: The role to get person type for.
        apply_fallback: If True, will try to infer from category metadata
                       and default to "individual" if not found.

    Returns:
        The person type string or None if not determinable.
    """
    # 1. Check party_types mapping first (the primary source)
    if session.party_types and role in session.party_types:
        return session.party_types[role]

    # 2. Check if role matches current session context
    if role == session.role and session.person_type:
        return session.person_type

    # 3. Apply fallback logic if requested
    if not apply_fallback:
        return None

    fallback_type = None

    # Try to get from category metadata
    if session.category_id:
        try:
            category = category_store.get(session.category_id)
            if category:
                meta = load_meta(category)
                role_meta = (meta.get("roles") or {}).get(role) or {}

                # 1. Check for explicit default_person_type in role metadata
                default_type = role_meta.get("default_person_type")
                if default_type:
                    fallback_type = default_type
                else:
                    # 2. Use first allowed type as fallback
                    allowed = role_meta.get("allowed_person_types") or []
                    if allowed:
                        fallback_type = allowed[0]
        except (KeyError, TypeError, ValueError, AttributeError):
            pass

    # Ultimate fallback: first available party_module or "individual"
    if not fallback_type and session.category_id:
        try:
            category = category_store.get(session.category_id)
            if category:
                meta = load_meta(category)
                party_modules = meta.get("party_modules") or {}
                if party_modules:
                    fallback_type = next(iter(party_modules.keys()))
        except (KeyError, TypeError, ValueError, AttributeError):
            pass

    return fallback_type or "individual"


def update_session_field(
    session: Session,
    field: str,
    value: str,
    role: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[str], FieldState]:
    """Update a field in the session with validation and state recalculation.

    Args:
        session: The session object to update.
        field: The field name (e.g. "iban", "name").
        value: The raw value to set.
        role: Optional role override. If None, uses session.role.
        tags: Optional PII tags for history tracking.
        context: Optional context (user_id, source, etc.) for audit logging.

    Returns:
        Tuple[success, error_message, field_state]
    """
    ctx = context or {}
    raw_value = "" if value is None else str(value)

    # Block any edits once the contract is fully signed (immutability after completion)
    if session.is_fully_signed:
        return (
            False,
            "Документ вже повністю підписаний. Редагування неможливе.",
            FieldState(status="error", error="Fully signed"),
        )

    # 1. Determine Context (Entity vs Party Field)
    if not session.category_id:
        return (
            False,
            "Спочатку потрібно обрати категорію (set_category).",
            FieldState(status="error", error="No category"),
        )

    entities = {e.field: e for e in list_entities(session.category_id)}
    entity = entities.get(field)
    is_party_field = False
    effective_role = None

    if entity is None:
        # It must be a party field
        effective_role = role or session.role
        if not effective_role:
            return (
                False,
                "Спочатку потрібно обрати роль (set_party_context) або передати її явно.",
                FieldState(status="error", error="Role not determined"),
            )

        # Use centralized function for determining person type with fallback
        effective_person_type = get_effective_person_type(
            session, effective_role, apply_fallback=True
        )

        # Store the fallback type if it was applied
        if session.party_types is None:
            session.party_types = {}
        session.party_types.setdefault(effective_role, effective_person_type)

        party_fields_map = {
            f.field: f
            for f in list_party_fields(session.category_id, effective_person_type)
        }
        party_meta = party_fields_map.get(field)
        if party_meta is None:
            return (
                False,
                "Поле не належить до обраної категорії.",
                FieldState(status="error", error="Unknown field"),
            )
        is_party_field = True
    else:
        # Contract field
        pass

    # 0. Порожнє значення для обов'язкового поля — це помилка
    is_required = True
    if entity:
        is_required = entity.required
    elif is_party_field and party_meta is not None:
        is_required = party_meta.required

    error_override = None
    if is_required and not raw_value.strip():
        error_override = "Значення не може бути порожнім."

    # 2. Check Signature Constraints
    # If CURRENT role has signed, they cannot edit.
    if session.signatures.get(effective_role or session.role):
        return (
            False,
            "Ви вже підписали цей документ. Редагування заборонено.",
            FieldState(status="error", error="Signed by user"),
        )

    # If ANY OTHER role has signed, we must invalidate their signatures.
    # We will do this AFTER validation, only if the update is valid.

    # 3. Determine Value Type & Validate
    value_type = "text"
    if entity:
        value_type = entity.type
    elif is_party_field:
        # Use centralized heuristic for inferring type from field name
        value_type = infer_value_type(field)

    # Для опційних полів з пустим значенням пропускаємо валідацію
    if not is_required and not raw_value.strip():
        normalized, error = "", None
    else:
        normalized, error = validate_value(value_type, value)
    if error_override:
        error = error_override
        normalized = raw_value

    # 3. Update Field State
    if is_party_field:
        if not effective_role:
            return (
                False,
                "Role not determined.",
                FieldState(status="error", error="Role missing"),
            )

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

    if is_party_field and effective_role:
        session.party_fields[effective_role][field] = fs
    else:
        session.contract_fields[field] = fs

    # 4. Update History (all_data)
    all_data = session.all_data or {}
    key = field
    if is_party_field and effective_role:
        key = f"{effective_role}.{field}"

    entry = all_data.get(key) or {}
    if error is None:
        entry["current"] = normalized
    entry["validated"] = error is None
    entry["source"] = ctx.get("source", "chat" if tags is not None else "api")
    all_data[key] = entry

    # Add global history event
    session.history.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "field_update",
            "key": key,
            "user_id": ctx.get("user_id"),
            "role": effective_role or session.role,
            "value": value,
            "normalized": normalized if error is None else None,
            "valid": error is None,
            "source": entry["source"],
        }
    )

    # Also store flat key for simple access if unique (backward compat)
    # But be careful about collisions.
    # The builder uses specific keys, so we should ensure we populate what builder expects.
    # Builder expects keys from list_entities and list_party_fields.
    # If it's a party field, builder constructs key as "{role}.{field}".
    # So 'key' variable above is correct.
    session.all_data = all_data

    # 5. Recalculate Session State
    is_ready = validate_session_readiness(session)
    session.can_build_contract = is_ready
    if is_ready:
        session.state = SessionState.READY_TO_BUILD
    else:
        session.state = SessionState.COLLECTING_FIELDS

    # 6. Update Progress
    _update_progress(session)

    # 7. Invalidate Signatures of OTHER parties
    if ok:
        # If we successfully updated a field, any existing signatures from
        # OTHER parties are now invalid because the document content changed.
        invalidated_roles = []
        for r, signed in session.signatures.items():
            if signed and r != (effective_role or session.role):
                session.signatures[r] = False
                invalidated_roles.append(r)

        if invalidated_roles:
            logger.info(
                "update_session_field: Invalidated signatures for roles=%s "
                "due to update by %s",
                invalidated_roles,
                effective_role or session.role,
            )
            # Optionally log to history as separate events? Skip for now.

    return ok, error, fs


def _update_progress(session: Session) -> None:
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


def set_party_type(session: Session, role: str, person_type: str) -> None:
    """
    Sets the person type for a role and clears fields if type changed.
    """
    # Update current context
    session.role = role
    session.person_type = person_type

    if session.party_types is None:
        session.party_types = {}

    old_type = session.party_types.get(role)

    # Update mapping
    session.party_types[role] = person_type

    # If type changed, clear old fields for this role to avoid dirty state
    if old_type and old_type != person_type:
        logger.info(
            "set_party_type: Clearing fields for role=%s due to type change %s -> %s",
            role, old_type, person_type
        )
        if role in session.party_fields:
            session.party_fields[role].clear()

        # Also clear from all_data?
        # all_data keys are like "{role}.{field}".
        # We should find all keys starting with "{role}." and remove them?
        # Or keep them in history but mark as invalid?
        # Removing them is cleaner for "current" state.
        # But we might want to keep history.
        # Let's just clear them from all_data to be safe and clean.
        prefix = f"{role}."
        keys_to_remove = [k for k in session.all_data.keys() if k.startswith(prefix)]
        for k in keys_to_remove:
            del session.all_data[k]

        # Invalidate signatures for this role (and re-evaluate state)
        if role in session.signatures:
            logger.info(
                "set_party_type: Invalidating signature for role=%s due to type change",
                role,
            )
            session.signatures[role] = False

        # Re-calculate readiness
        is_ready = validate_session_readiness(session)
        session.can_build_contract = is_ready
        if is_ready:
            session.state = SessionState.READY_TO_BUILD
        else:
            session.state = SessionState.COLLECTING_FIELDS

        _update_progress(session)


def set_session_template(session: Session, template_id: str) -> None:
    """
    Sets the template for the session and updates state.
    Does NOT validate if template belongs to category (assumed caller checked or we check here).
    """
    # Ideally we should validate that template_id belongs to session.category_id
    # But to avoid circular imports or heavy loading, we might skip it or do it lightly.
    # The tools usually check this. Let's assume valid input or add check if needed.
    if session.template_id == template_id:
        return

    session.template_id = template_id
    session.state = SessionState.TEMPLATE_SELECTED

    # Reset fields?
    # If we switch template within same category, maybe keep fields?
    # But different templates might have different fields.
    # For safety, we might want to warn or clear.
    # Current logic in tools didn't clear fields.
    # Let's keep it as is (preserve data), but maybe re-validate readiness?
    is_ready = validate_session_readiness(session)
    session.can_build_contract = is_ready
    if is_ready:
        session.state = SessionState.READY_TO_BUILD

    # If not ready, stay at TEMPLATE_SELECTED (or COLLECTING_FIELDS if we had data?)
    # Actually, if we just selected template, we are likely at TEMPLATE_SELECTED.
    # Unless we already have enough data to be ready.
    _update_progress(session)


def claim_session_role(session: Session, role: str, user_id: str) -> None:
    """
    Claims a role for the given user_id.

    Rules:
    1. Role must exist in the category metadata.
    2. Role must not be occupied by another user.
    3. A user can own only one role within a session (unless filling_mode == "full").
    """
    if not role:
        raise ValueError("Role must be specified.")
    if not user_id:
        raise ValueError("User ID must be specified.")

    if session.role_owners is None:
        session.role_owners = {}

    if not session.category_id:
        raise ValueError("Category is not set for the session.")

    # category_store and load_meta already imported at module level
    category = category_store.get(session.category_id)
    if not category:
        raise ValueError(f"Category '{session.category_id}' not found.")

    meta = load_meta(category)
    roles_meta = meta.get("roles") or {}
    if role not in roles_meta:
        raise ValueError(f"Role '{role}' does not exist in category '{session.category_id}'.")

    # Один користувач може володіти лише однією роллю в сесії.
    # В режимі "full" він може РЕДАГУВАТИ дані інших ролей (через can_edit_party_field),
    # але не може ВОЛОДІТИ кількома ролями.
    for existing_role, uid in (session.role_owners or {}).items():
        if uid == user_id and existing_role == role:
            # Already owns this role; nothing to change.
            return
        if uid == user_id and existing_role != role:
            logger.warning(
                "User %s already owns role %s in session %s",
                user_id, existing_role, session.session_id,
            )
            raise PermissionError(f"User already owns role '{existing_role}'.")

    current_owner = (session.role_owners or {}).get(role)
    if current_owner and current_owner != user_id:
        logger.warning(
            "Role %s already claimed by %s in session %s",
            role, current_owner, session.session_id,
        )
        raise PermissionError(f"Role '{role}' is already claimed.")

    session.role_owners[role] = user_id


def get_user_roles(session: Session, user_id: str) -> list[str]:
    """
    Returns list of roles claimed by user_id in the session.
    """
    if not user_id:
        return []
    return [
        role for role, owner in (session.role_owners or {}).items()
        if owner == user_id
    ]


def can_edit_party_field(
    session: Session,
    *,
    acting_user_id: str,
    target_role: str,
) -> bool:
    """
    Access control for editing party fields.
    - Owner of the role can edit.
    - If role unclaimed: creator in FULL mode can prefill.
    """
    if not session.category_id:
        return False

    owner = (session.role_owners or {}).get(target_role)
    if owner == acting_user_id:
        return True
    if owner and owner != acting_user_id:
        return False

    # Role is unclaimed
    if session.creator_user_id == acting_user_id and session.filling_mode == FillingMode.FULL:
        return True

    return False


def can_edit_contract_field(
    session: Session,
    *,
    acting_user_id: str,
    field_name: str,  # noqa: ARG001
) -> bool:
    """Access control for editing contract fields.

    Any participant (role owner) can edit.
    Creator can edit even if roles are not claimed yet.
    """
    del field_name  # unused, kept for API consistency
    if not session.category_id:
        return False

    user_roles = get_user_roles(session, acting_user_id)

    # Creator can edit before roles are claimed
    if not user_roles and session.creator_user_id == acting_user_id:
        return True

    if not session.role_owners:
        return session.creator_user_id == acting_user_id

    return bool(user_roles)
