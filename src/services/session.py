from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from datetime import datetime

from src.common.logging import get_logger
from src.sessions.models import Session, FieldState, SessionState
from src.validators.core import validate_value
from src.categories.index import list_entities, list_party_fields
from src.services.fields import validate_session_readiness, get_required_fields

logger = get_logger(__name__)

def update_session_field(
    session: Session,
    field: str,
    value: str,
    role: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[str], FieldState]:
    """
    Updates a single field in the session with validation, history tracking, and state recalculation.
    
    Args:
        session: The session object to update.
        field: The field name (e.g. "iban", "name").
        value: The raw value to set.
        role: Optional role override. If None, uses session.role.
        tags: Optional PII tags for history tracking.
        context: Optional context (client_id, source, etc.) for audit logging.

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
        return False, "Спочатку потрібно обрати категорію (set_category).", FieldState(status="error", error="No category")

    entities = {e.field: e for e in list_entities(session.category_id)}
    entity = entities.get(field)
    is_party_field = False
    effective_role = None

    if entity is None:
        # It must be a party field
        effective_role = role or session.role
        if not effective_role:
             return False, "Спочатку потрібно обрати роль (set_party_context) або передати її явно.", FieldState(status="error", error="Role not determined")

        effective_person_type = None
        if session.party_types and effective_role in session.party_types:
            effective_person_type = session.party_types[effective_role]
        elif effective_role == session.role:
            effective_person_type = session.person_type

        if not effective_person_type:
            return False, f"Невідомий тип особи для ролі {effective_role}. Встановіть контекст або тип особи.", FieldState(status="error", error="Person type unknown")

        party_fields_map = {
            f.field: f
            for f in list_party_fields(session.category_id, effective_person_type)
        }
        party_meta = party_fields_map.get(field)
        if party_meta is None:
            return False, "Поле не належить до обраної категорії.", FieldState(status="error", error="Unknown field")
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
         return False, "Ви вже підписали цей документ. Редагування заборонено.", FieldState(status="error", error="Signed by user")

    # If ANY OTHER role has signed, we must invalidate their signatures.
    # We will do this AFTER validation, only if the update is valid.

    # 3. Determine Value Type & Validate
    value_type = "text"
    if entity:
        value_type = entity.type
    elif is_party_field:
         # Heuristic mapping for party fields (duplicated from UpsertFieldTool, but centralized here)
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

    normalized, error = validate_value(value_type, value)
    if error_override:
        error = error_override
        normalized = raw_value

    # 3. Update Field State
    if is_party_field:
        if not effective_role:
             return False, "Role not determined.", FieldState(status="error", error="Role missing")

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
    history = entry.get("history") or []
    
    # Add history entry
    history.append(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "client_id": ctx.get("client_id"),
            "role": effective_role or session.role,
            "source": ctx.get("source", "chat" if tags is not None else "api"),
            "value": value,
            "normalized": normalized if error is None else None,
            "valid": error is None,
            "tags": tags,  # Store tags if available
        }
    )
    
    # Update current value if valid (or if it's the first value?)
    # Logic: Always update current to what user typed? Or only if valid?
    # Original logic: entry["current"] = normalized if error is None else entry.get("current")
    # This means if user types invalid value, we KEEP the old valid value in 'current'.
    # But we store the invalid attempt in history.
    if error is None:
        entry["current"] = normalized
    
    entry["validated"] = error is None
    entry["source"] = "chat" if tags is not None else "api"
    entry["history"] = history
    
    all_data[key] = entry
    
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
        # If we successfully updated a field, any existing signatures from OTHER parties are now invalid
        # because the document content has changed.
        invalidated_roles = []
        for r, signed in session.signatures.items():
            if signed and r != (effective_role or session.role):
                session.signatures[r] = False
                invalidated_roles.append(r)
        
        if invalidated_roles:
            logger.info(
                "update_session_field: Invalidated signatures for roles=%s due to update by %s",
                invalidated_roles, effective_role or session.role
            )
            # Ideally we should notify them or add to history?
            # For now, just logging is enough. The UI will show them as unsigned.

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
            logger.info("set_party_type: Invalidating signature for role=%s due to type change", role)
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


def claim_session_role(session: Session, role: str, user_id: str) -> bool:
    """
    Attempts to claim a role for a specific user.
    Returns True if successful, False otherwise.
    """
    if not role:
        raise ValueError("Role must be specified.")
    if not user_id:
        raise ValueError("User ID must be specified.")

    # Usually strict 1 user = 1 role.
    # But maybe for testing we allow one user to play both?
    # Let's enforce 1 role per user for strict mode.
    # Iterate over party_users to see if user_id is there
    for r, uid in session.party_users.items():
        if uid == user_id and r == role:
            # User already has THIS role. That's fine.
            return True
        if uid == user_id and r != role:
             # User trying to claim a second role
             # If filling_mode is 'full', we allow one user to have multiple roles.
             if session.filling_mode == "full":
                 continue
             # Otherwise, strict mode: one role per user.
             logger.warning(f"User {user_id} already has role {r}, cannot claim {role}")
             return False
    
    # Check if role is taken by someone else
    current_owner = session.party_users.get(role)
    if current_owner and current_owner != user_id:
        logger.warning(f"Role {role} is already taken by {current_owner}")
        return False

    # Claim it
    session.party_users[role] = user_id
    return True
