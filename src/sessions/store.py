from __future__ import annotations

from dataclasses import asdict
from typing import Optional, Generator
from datetime import datetime
import random
import string
from contextlib import contextmanager

from src.common.config import settings
from src.common.errors import SessionNotFoundError
from src.documents.user_document import save_user_document
from src.sessions.models import FieldState, Session, SessionState
from src.storage.fs import read_json, session_answers_path, write_json, FileLock


def list_user_sessions(client_id: str) -> list[Session]:
    """
    Lists all sessions where the given client_id is a participant.
    """
    sessions = []
    if not settings.sessions_root.exists():
        return []

    for file_path in settings.sessions_root.glob("session_*.json"):
        try:
            # Read without lock for speed/listing
            data = read_json(file_path)
            party_users = data.get("party_users") or {}
            
            # Check if client is a participant
            if client_id in party_users.values():
                sessions.append(_from_dict(data))
        except Exception:
            continue

    # Sort by updated_at desc
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions


def generate_readable_id(prefix: str = "session") -> str:
    """
    Генерує унікальний ID (UUID).
    Аргумент prefix залишено для сумісності, але ігнорується.
    """
    import uuid
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
        # is_signed removed from model, replaced by signatures dict
        signatures=data.get("signatures") or {},
        party_users=data.get("party_users") or {},
        party_types=data.get("party_types") or {},
        filling_mode=data.get("filling_mode", "partial"),
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
    sign_history = data.get("sign_history")
    if isinstance(sign_history, list):
        session.sign_history = sign_history
    return session


def get_or_create_session(session_id: str, user_id: Optional[str] = None) -> Session:
    path = session_answers_path(session_id)
    
    # Ensure parent dir exists
    path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(path):
        if path.exists():
            # File exists, load it safely under lock
            data = read_json(path)
            return _from_dict(data)

        # File does not exist, create new session
        session = Session(session_id=session_id, user_id=user_id)
        # Save with locked_by_caller=True since we already hold the lock
        save_session(session, locked_by_caller=True)
        return session


def load_session(session_id: str) -> Session:
    """
    Loads session without locking. Use only for read-only operations.
    For modifications, use transactional_session.
    """
    path = session_answers_path(session_id)
    if not path.exists():
        raise SessionNotFoundError(f"Session '{session_id}' not found")
    data = read_json(path)
    return _from_dict(data)


def save_session(session: Session, locked_by_caller: bool = False) -> None:
    """
    Saves session.
    If locked_by_caller=True, assumes file is already locked by context manager.
    """
    # Update updated_at to now
    session.updated_at = datetime.now()

    path = session_answers_path(session.session_id)
    data = asdict(session)
    
    # Ensure party_users and party_types are serialized (asdict should handle it if they are dicts)
    # But let's be explicit just in case
    data["party_users"] = session.party_users
    data["party_types"] = session.party_types
    data["filling_mode"] = session.filling_mode
    data["signatures"] = session.signatures
    data["sign_history"] = session.sign_history
    
    # Serialize datetime
    data["updated_at"] = session.updated_at.isoformat()

    # Enum to value
    data["state"] = session.state.value
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

    write_json(path, data, locked_by_caller=locked_by_caller)
    # Додатково синхронізуємо user-document у форматі example_user_document.json
    try:
        save_user_document(session)
    except Exception:
        # Не ламаємо основний шлях збереження сесії, якщо побудова
        # user-document тимчасово не вдалася.
        pass

@contextmanager
def transactional_session(session_id: str) -> Generator[Session, None, None]:
    """
    Context manager for atomic read-modify-write session operations.
    Acquires a lock, loads the session, yields it, and saves it back upon exit.
    """
    path = session_answers_path(session_id)
    # Ensure directory exists (for new sessions/files)
    path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(path):
        # 1. Load
        if not path.exists():
             raise SessionNotFoundError(f"Session '{session_id}' not found")

        data = read_json(path)
        session = _from_dict(data)

        # 2. Yield
        yield session

        # 3. Save (with locked_by_caller=True)
        save_session(session, locked_by_caller=True)
