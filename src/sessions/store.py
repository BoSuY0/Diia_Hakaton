from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from src.common.errors import SessionNotFoundError
from src.documents.user_document import save_user_document
from src.sessions.models import FieldState, Session, SessionState
from src.storage.fs import read_json, session_answers_path, write_json

import random
import string

def generate_readable_id(prefix: str = "session") -> str:
    """
    Генерує читабельний ID у форматі {prefix}_{random_digits}.
    Наприклад: lease_flat_59210
    """
    # 5 випадкових цифр
    suffix = "".join(random.choices(string.digits, k=5))
    return f"{prefix}_{suffix}"

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

    session = Session(
        session_id=data["session_id"],
        user_id=data.get("user_id"),
        locale=data.get("locale", "uk"),
        category_id=data.get("category_id"),
        template_id=data.get("template_id"),
        role=data.get("role"),
        person_type=data.get("person_type"),
        state=SessionState(data.get("state", SessionState.IDLE.value)),
        party_fields=party_fields,
        contract_fields=contract_fields,
        can_build_contract=bool(data.get("can_build_contract", False)),
        party_types=data.get("party_types") or {},
    )
    # Додаткові поля (routing, all_data, progress) — опційні, для зворотної сумісності
    routing = data.get("routing")
    if isinstance(routing, dict):
        session.routing = routing
    all_data = data.get("all_data")
    if isinstance(all_data, dict):
        session.all_data = all_data
    progress = data.get("progress")
    if isinstance(progress, dict):
        session.progress = progress
    return session


def get_or_create_session(session_id: str, user_id: Optional[str] = None) -> Session:
    path = session_answers_path(session_id)
    if path.exists():
        data = read_json(path)
        return _from_dict(data)
    session = Session(session_id=session_id, user_id=user_id)
    save_session(session)
    return session


def load_session(session_id: str) -> Session:
    path = session_answers_path(session_id)
    if not path.exists():
        raise SessionNotFoundError(f"Session '{session_id}' not found")
    data = read_json(path)
    return _from_dict(data)


def save_session(session: Session) -> None:
    path = session_answers_path(session.session_id)
    data = asdict(session)
    # Enum to value
    data["state"] = session.state.value
    # Зберігаємо статус полів як bool (True/False) для читабельного JSON.
    # Зберігаємо статус полів як bool (True/False) для читабельного JSON.
    # 1. Contract Fields (Flat)
    c_fields = data.get("contract_fields") or {}
    for key, value in c_fields.items():
        raw_status = value.get("status")
        if isinstance(raw_status, bool):
            continue
        status_str = str(raw_status or "empty")
        error = value.get("error")
        value["status"] = bool(status_str == "ok" and error is None)

    # 2. Party Fields (Nested: Role -> Field)
    p_fields = data.get("party_fields") or {}
    for role, fields_dict in p_fields.items():
        if not isinstance(fields_dict, dict):
            continue
        for key, value in fields_dict.items():
            raw_status = value.get("status")
            if isinstance(raw_status, bool):
                continue
            status_str = str(raw_status or "empty")
            error = value.get("error")
            value["status"] = bool(status_str == "ok" and error is None)

    write_json(path, data)
    # Додатково синхронізуємо user-document у форматі example_user_document.json
    try:
        save_user_document(session)
    except Exception:
        # Не ламаємо основний шлях збереження сесії, якщо побудова
        # user-document тимчасово не вдалася.
        pass
