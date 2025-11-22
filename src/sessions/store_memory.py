from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Generator

from src.common.config import settings
from src.common.errors import SessionNotFoundError
from src.documents.user_document import save_user_document
from src.sessions.models import Session
from src.sessions.store_utils import _from_dict, session_to_dict

_sessions: dict[str, str] = {}
_expires_at: dict[str, datetime] = {}
_session_users: dict[str, set[str]] = {}
_user_index: dict[str, dict[str, int]] = {}
_locks: dict[str, threading.RLock] = {}
_global_lock = threading.RLock()


def _session_ttl_seconds() -> int:
    try:
        ttl_hours = int(getattr(settings, "session_ttl_hours", 24))
    except (TypeError, ValueError):
        ttl_hours = 24
    return max(ttl_hours * 3600, 1)


def _get_lock(session_id: str) -> threading.RLock:
    with _global_lock:
        lock = _locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _locks[session_id] = lock
        return lock


def _evict_if_expired(session_id: str) -> bool:
    expire = _expires_at.get(session_id)
    if expire and datetime.now() > expire:
        _remove_session(session_id)
        return True
    return False


def _remove_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
    _expires_at.pop(session_id, None)
    _session_users.pop(session_id, None)
    for idx in _user_index.values():
        idx.pop(session_id, None)
    # Cleanup empty user_index entries
    empty_users = [uid for uid, idx in _user_index.items() if not idx]
    for uid in empty_users:
        _user_index.pop(uid, None)


def _update_indexes(session: Session) -> None:
    ts = session.updated_at.timestamp()
    new_users = {uid for uid in (session.party_users or {}).values() if uid}
    prev_users = _session_users.get(session.session_id, set())

    removed = prev_users - new_users
    for uid in removed:
        if uid in _user_index:
            _user_index[uid].pop(session.session_id, None)

    for uid in new_users:
        idx = _user_index.setdefault(uid, {})
        idx[session.session_id] = ts

    _session_users[session.session_id] = new_users


def save_session(session: Session) -> None:
    session.updated_at = datetime.now()
    data = session_to_dict(session)
    payload = json.dumps(data, ensure_ascii=False)
    ttl_seconds = _session_ttl_seconds()
    expire_at = session.updated_at + timedelta(seconds=ttl_seconds)

    with _global_lock:
        _sessions[session.session_id] = payload
        _expires_at[session.session_id] = expire_at
        _update_indexes(session)

    try:
        save_user_document(session)
    except Exception:
        pass


def load_session(session_id: str) -> Session:
    with _global_lock:
        if _evict_if_expired(session_id):
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        payload = _sessions.get(session_id)
    if payload is None:
        raise SessionNotFoundError(f"Session '{session_id}' not found")
    data = json.loads(payload)
    return _from_dict(data)


def get_or_create_session(session_id: str, user_id: str | None = None) -> Session:
    try:
        return load_session(session_id)
    except SessionNotFoundError:
        session = Session(session_id=session_id, user_id=user_id)
        save_session(session)
        return session


@contextmanager
def transactional_session(session_id: str) -> Generator[Session, None, None]:
    lock = _get_lock(session_id)
    with lock:
        session = load_session(session_id)
        yield session
        save_session(session)


def list_user_sessions(client_id: str) -> list[Session]:
    if not client_id:
        return []

    with _global_lock:
        idx = _user_index.get(client_id, {})
        session_ids = sorted(idx.keys(), key=lambda sid: idx[sid], reverse=True)

    sessions: list[Session] = []
    stale_ids: list[str] = []
    for sid in session_ids:
        try:
            s = load_session(sid)
        except SessionNotFoundError:
            stale_ids.append(sid)
            continue
        if client_id not in (s.party_users or {}).values():
            stale_ids.append(sid)
            continue
        sessions.append(s)

    if stale_ids:
        with _global_lock:
            for sid in stale_ids:
                if client_id in _user_index:
                    _user_index[client_id].pop(sid, None)
            if client_id in _user_index and not _user_index[client_id]:
                _user_index.pop(client_id, None)

    return sessions


def _reset_for_tests() -> None:
    with _global_lock:
        _sessions.clear()
        _expires_at.clear()
        _session_users.clear()
        _user_index.clear()
        _locks.clear()
