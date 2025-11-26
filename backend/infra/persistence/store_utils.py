"""Utility functions for session serialization and deserialization."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import uuid

from backend.domain.sessions.models import FieldState, Session, SessionState


def _parse_field_status(raw_status, error: str | None) -> str:
    """
    Parse field status from various formats to canonical string format.
    
    Canonical statuses: "ok", "error", "empty"
    
    Handles:
    - bool: True -> "ok", False -> "error" if error exists, else "empty"
    - str: returned as-is if valid, defaults to "empty"
    """
    if isinstance(raw_status, bool):
        if raw_status:
            return "ok"
        return "error" if error else "empty"

    if isinstance(raw_status, str) and raw_status in ("ok", "error", "empty"):
        return raw_status

    return "empty"


def generate_readable_id(_prefix: str = "session") -> str:
    """
    Generate a unique session ID (UUID).

    Args:
        _prefix: Ignored, kept for backward compatibility.

    Returns:
        A UUID string.
    """
    return str(uuid.uuid4())


def _from_dict(data: dict) -> Session:
    # Відновлюємо вкладені FieldState (новий формат: party_fields[role][field])
    raw_party_fields = data.get("party_fields") or {}
    party_fields: dict[str, dict[str, FieldState]] = {}

    for role, fields_dict in raw_party_fields.items():
        if not isinstance(fields_dict, dict):
            continue
        role_fields = {}
        for key, value in fields_dict.items():
            error = value.get("error")
            status = _parse_field_status(value.get("status"), error)
            role_fields[key] = FieldState(status=status, error=error)
        party_fields[role] = role_fields

    # Підтримка попереднього формату: якщо немає contract_fields, читаємо legacy "fields"
    raw_contract_fields = data.get("contract_fields")
    if raw_contract_fields is None:
        raw_contract_fields = data.get("fields") or {}
    contract_fields: dict[str, FieldState] = {}
    for key, value in raw_contract_fields.items():
        error = value.get("error")
        status = _parse_field_status(value.get("status"), error)
        contract_fields[key] = FieldState(status=status, error=error)

    # Deserialize updated_at
    updated_at_str = data.get("updated_at")
    if updated_at_str:
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            updated_at = datetime.now(timezone.utc)
    else:
        updated_at = datetime.now(timezone.utc)

    session = Session(
        session_id=data["session_id"],
        creator_user_id=data.get("creator_user_id") or data.get("user_id"),
        role_owners=data.get("role_owners") or data.get("party_users") or {},
        updated_at=updated_at,
        locale=data.get("locale", "uk"),
        category_id=data.get("category_id"),
        template_id=data.get("template_id"),
        role=data.get("role"),
        person_type=data.get("person_type"),
        state=SessionState(data.get("state", SessionState.IDLE.value)),
        party_fields=party_fields,
        contract_fields=contract_fields,
        can_build_contract=bool(data.get("can_build_contract", False)),
        signatures=data.get("signatures") or {},
        party_types=data.get("party_types") or {},
        filling_mode=data.get("filling_mode", "partial"),
        required_roles=data.get("required_roles") or [],
    )
    routing = data.get("routing")
    if isinstance(routing, dict):
        session.routing = routing
    all_data = data.get("all_data")
    if isinstance(all_data, dict):
        session.all_data = all_data
    progress = data.get("progress")
    if isinstance(progress, dict):
        session.progress = progress
    history = data.get("history")
    merged_history: list[dict] = []
    if isinstance(history, list):
        merged_history.extend(history)

    legacy_sign_history = data.get("sign_history")
    if isinstance(legacy_sign_history, list):
        for evt in legacy_sign_history:
            if not isinstance(evt, dict):
                continue
            ts = evt.get("timestamp") or evt.get("ts")
            ts = ts or datetime.now(timezone.utc).isoformat()
            merged_history.append(
                {
                    "ts": ts,
                    "type": "sign",
                    "user_id": evt.get("user_id"),
                    "roles": evt.get("roles", []),
                    "state": evt.get("state"),
                }
            )

    if merged_history:
        session.history = merged_history
    return session


# NOTE: Field statuses are now stored as strings ("ok", "error", "empty")
# for consistency. Legacy boolean format is still read via _parse_field_status.


def session_to_dict(session: Session) -> dict:
    """Convert a Session object to a dictionary for serialization."""
    data = asdict(session)
    data["creator_user_id"] = session.creator_user_id
    data["role_owners"] = session.role_owners
    # party_users kept for backward compatibility in persisted payloads
    data["party_users"] = session.role_owners
    data["party_types"] = session.party_types
    data["filling_mode"] = session.filling_mode
    data["signatures"] = session.signatures
    data["required_roles"] = session.required_roles
    data["history"] = session.history
    data["updated_at"] = session.updated_at.isoformat()
    data["state"] = session.state.value
    # Field statuses are stored as strings ("ok", "error", "empty")
    return data
