from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional
import uuid

from src.sessions.models import FieldState, Session, SessionState


def generate_readable_id(prefix: str = "session") -> str:
    """
    Генерує унікальний ID (UUID).
    Аргумент prefix залишено для сумісності, але ігнорується.
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
            raw_status = value.get("status")
            if isinstance(raw_status, bool):
                if raw_status:
                    status = "ok"
                else:
                    status = "error" if value.get("error") else "empty"
            else:
                status = value.get("status", "empty")
            role_fields[key] = FieldState(
                status=status,
                error=value.get("error"),
            )
        party_fields[role] = role_fields

    # Підтримка попереднього формату: якщо немає contract_fields, читаємо legacy "fields"
    raw_contract_fields = data.get("contract_fields")
    if raw_contract_fields is None:
        raw_contract_fields = data.get("fields") or {}
    contract_fields: dict[str, FieldState] = {}
    for key, value in raw_contract_fields.items():
        raw_status = value.get("status")
        if isinstance(raw_status, bool):
            if raw_status:
                status = "ok"
            else:
                status = "error" if value.get("error") else "empty"
        else:
            status = value.get("status", "empty")
        contract_fields[key] = FieldState(
            status=status,
            error=value.get("error"),
        )

    # Deserialize updated_at
    updated_at_str = data.get("updated_at")
    updated_at = datetime.fromisoformat(updated_at_str) if updated_at_str else datetime.now()

    session = Session(
        session_id=data["session_id"],
        user_id=data.get("user_id"),
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
        party_users=data.get("party_users") or {},
        party_types=data.get("party_types") or {},
        filling_mode=data.get("filling_mode", "partial"),
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
    sign_history = data.get("sign_history")
    if isinstance(sign_history, list):
        session.sign_history = sign_history
    return session


def _normalize_field_statuses(data: dict) -> None:
    """
    Mutates serialized session data so FieldState.status is stored as bools for readability.
    """
    c_fields = data.get("contract_fields") or {}
    for key, value in c_fields.items():
        if not isinstance(value, dict):
            continue
        raw_status = value.get("status")
        if isinstance(raw_status, bool):
            continue
        status_str = str(raw_status or "empty")
        error = value.get("error")
        value["status"] = bool(status_str == "ok" and error is None)

    p_fields = data.get("party_fields") or {}
    for role, fields_dict in p_fields.items():
        if not isinstance(fields_dict, dict):
            continue
        for key, value in fields_dict.items():
            if not isinstance(value, dict):
                continue
            raw_status = value.get("status")
            if isinstance(raw_status, bool):
                continue
            status_str = str(raw_status or "empty")
            error = value.get("error")
            value["status"] = bool(status_str == "ok" and error is None)


def session_to_dict(session: Session) -> dict:
    data = asdict(session)
    data["party_users"] = session.party_users
    data["party_types"] = session.party_types
    data["filling_mode"] = session.filling_mode
    data["signatures"] = session.signatures
    data["sign_history"] = session.sign_history
    data["updated_at"] = session.updated_at.isoformat()
    data["state"] = session.state.value
    _normalize_field_statuses(data)
    return data
