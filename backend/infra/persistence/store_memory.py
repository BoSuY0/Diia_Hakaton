"""In-memory session store implementation."""
from __future__ import annotations

import json
import asyncio
import threading
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

from backend.infra.config.settings import settings
from backend.shared.errors import SessionNotFoundError
from backend.domain.documents.user_document import save_user_document
from backend.domain.sessions.models import Session
from backend.infra.persistence.store_utils import _from_dict, session_to_dict
from backend.shared.async_utils import run_sync

_sessions: dict[str, str] = {}
_expires_at: dict[str, datetime] = {}
_session_users: dict[str, set[str]] = {}
_user_index: dict[str, dict[str, int]] = {}
_locks: dict[str, threading.RLock] = {}
_async_locks: dict[str, asyncio.Lock] = {}
_global_lock = threading.RLock()
_async_global_lock = asyncio.Lock()


def _session_ttl_seconds(session) -> int:
    """Calculate session TTL in seconds."""
    try:
        from backend.domain.sessions.ttl import ttl_hours_for_session  # pylint: disable=import-outside-toplevel
        ttl_hours = ttl_hours_for_session(session)
    except (ImportError, AttributeError):
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


def _get_async_lock(session_id: str) -> asyncio.Lock:
    # Use global lock to ensure atomic check-and-create
    with _global_lock:
        if session_id not in _async_locks:
            _async_locks[session_id] = asyncio.Lock()
        return _async_locks[session_id]


def _evict_if_expired(session_id: str) -> bool:
    expire = _expires_at.get(session_id)
    if expire and datetime.now(timezone.utc) > expire:
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
    new_users = {uid for uid in (session.role_owners or {}).values() if uid}
    if session.creator_user_id:
        new_users.add(session.creator_user_id)
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
    """Save session to in-memory store."""
    session.updated_at = datetime.now(timezone.utc)
    data = session_to_dict(session)
    payload = json.dumps(data, ensure_ascii=False)
    ttl_seconds = _session_ttl_seconds(session)
    expire_at = session.updated_at + timedelta(seconds=ttl_seconds)

    with _global_lock:
        _sessions[session.session_id] = payload
        _expires_at[session.session_id] = expire_at
        _update_indexes(session)

    try:
        save_user_document(session)
    except (OSError, ValueError):
        pass


def load_session(session_id: str) -> Session:
    """Load session from in-memory store."""
    with _global_lock:
        if _evict_if_expired(session_id):
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        payload = _sessions.get(session_id)
    if payload is None:
        raise SessionNotFoundError(f"Session '{session_id}' not found")
    data = json.loads(payload)
    return _from_dict(data)


def get_or_create_session(session_id: str, user_id: str | None = None) -> Session:
    """Get existing session or create a new one."""
    try:
        return load_session(session_id)
    except SessionNotFoundError:
        session = Session(session_id=session_id, creator_user_id=user_id)
        save_session(session)
        return session


@contextmanager
def transactional_session(session_id: str) -> Generator[Session, None, None]:
    """Context manager for transactional session access."""
    lock = _get_lock(session_id)
    with lock:
        session = load_session(session_id)
        yield session
        save_session(session)


def list_user_sessions(user_id: str) -> list[Session]:
    """List all sessions for a user."""
    if not user_id:
        return []

    with _global_lock:
        idx = _user_index.get(user_id, {})
        session_ids = sorted(idx.keys(), key=lambda sid: idx[sid], reverse=True)

    sessions: list[Session] = []
    stale_ids: list[str] = []
    for sid in session_ids:
        try:
            s = load_session(sid)
        except SessionNotFoundError:
            stale_ids.append(sid)
            continue
        if user_id not in (s.role_owners or {}).values() and user_id != s.creator_user_id:
            stale_ids.append(sid)
            continue
        sessions.append(s)

    if stale_ids:
        with _global_lock:
            for sid in stale_ids:
                if user_id in _user_index:
                    _user_index[user_id].pop(sid, None)
            if user_id in _user_index and not _user_index[user_id]:
                _user_index.pop(user_id, None)

    return sessions


def _reset_for_tests() -> None:
    with _global_lock:
        _sessions.clear()
        _expires_at.clear()
        _session_users.clear()
        _user_index.clear()
        _locks.clear()


# Async variants (lightweight locking; reuses same in-memory structures)
async def asave_session(session: Session) -> None:
    """Save session to in-memory store (async)."""
    session.updated_at = datetime.now(timezone.utc)
    data = session_to_dict(session)
    payload = json.dumps(data, ensure_ascii=False)
    ttl_seconds = _session_ttl_seconds(session)
    expire_at = session.updated_at + timedelta(seconds=ttl_seconds)

    async with _async_global_lock:
        _sessions[session.session_id] = payload
        _expires_at[session.session_id] = expire_at
        _update_indexes(session)

    try:
        await run_sync(save_user_document, session)
    except (OSError, ValueError):
        pass


async def aload_session(session_id: str) -> Session:
    """Load session from in-memory store (async)."""
    async with _async_global_lock:
        if _evict_if_expired(session_id):
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        payload = _sessions.get(session_id)
    if payload is None:
        raise SessionNotFoundError(f"Session '{session_id}' not found")
    data = json.loads(payload)
    return _from_dict(data)


async def aget_or_create_session(session_id: str, user_id: str | None = None) -> Session:
    """Get existing session or create a new one (async)."""
    try:
        return await aload_session(session_id)
    except SessionNotFoundError:
        session = Session(session_id=session_id, creator_user_id=user_id)
        await asave_session(session)
        return session


@asynccontextmanager
async def atransactional_session(session_id: str):
    """Async context manager for transactional session access."""
    lock = _get_async_lock(session_id)
    async with lock:
        session = await aload_session(session_id)
        yield session
        await asave_session(session)


async def alist_user_sessions(user_id: str) -> list[Session]:
    """List all sessions for a user (async)."""
    if not user_id:
        return []

    async with _async_global_lock:
        idx = _user_index.get(user_id, {})
        session_ids = sorted(idx.keys(), key=lambda sid: idx[sid], reverse=True)

    sessions: list[Session] = []
    stale_ids: list[str] = []
    for sid in session_ids:
        try:
            s = await aload_session(sid)
        except SessionNotFoundError:
            stale_ids.append(sid)
            continue
        if user_id not in (s.role_owners or {}).values() and user_id != s.creator_user_id:
            stale_ids.append(sid)
            continue
        sessions.append(s)

    if stale_ids:
        async with _async_global_lock:
            for sid in stale_ids:
                if user_id in _user_index:
                    _user_index[user_id].pop(sid, None)
            if user_id in _user_index and not _user_index[user_id]:
                _user_index.pop(user_id, None)

    return sessions
