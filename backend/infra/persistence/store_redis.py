from __future__ import annotations

import json
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Generator, Any

from backend.infra.config.settings import settings
from backend.domain.sessions.ttl import ttl_hours_for_session
from backend.shared.errors import SessionNotFoundError
from backend.domain.documents.user_document import save_user_document_async
from backend.domain.sessions.models import Session
from backend.infra.persistence.store_utils import _from_dict, session_to_dict
from backend.infra.storage.redis_client import get_redis

SESSION_KEY_PREFIX = "session:"
USER_INDEX_PREFIX = "user_sessions:"
LOCK_PREFIX = "session_lock:"
DEFAULT_LOCK_TTL = 10
DEFAULT_LOCK_WAIT_TIMEOUT = 5


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _user_index_key(user_id: str) -> str:
    return f"{USER_INDEX_PREFIX}{user_id}"


def _lock_key(session_id: str) -> str:
    return f"{LOCK_PREFIX}{session_id}"


async def save_session(session: Session) -> None:
    redis = await get_redis()
    session.updated_at = datetime.now()

    data = session_to_dict(session)
    payload = json.dumps(data, ensure_ascii=False)
    ttl_seconds = max(ttl_hours_for_session(session) * 3600, 1)
    await redis.set(_session_key(session.session_id), payload, ex=ttl_seconds)

    role_owners = session.role_owners or {}
    if role_owners:
        ts = session.updated_at.timestamp()
        mapping = {session.session_id: ts}
        for uid in role_owners.values():
            if uid:
                await redis.zadd(_user_index_key(uid), mapping)

    try:
        await save_user_document_async(session)
    except Exception:
        pass


async def load_session(session_id: str) -> Session:
    redis = await get_redis()
    raw = await redis.get(_session_key(session_id))
    if raw is None:
        raise SessionNotFoundError(f"Session '{session_id}' not found")
    data = json.loads(raw)
    return _from_dict(data)


async def get_or_create_session(session_id: str, user_id: str | None = None) -> Session:
    try:
        return await load_session(session_id)
    except SessionNotFoundError:
        session = Session(session_id=session_id, creator_user_id=user_id)
        await save_session(session)
        return session


@asynccontextmanager
async def transactional_session(
    session_id: str,
    lock_ttl: int = DEFAULT_LOCK_TTL,
    wait_timeout: int = DEFAULT_LOCK_WAIT_TIMEOUT,
):
    redis = await get_redis()
    token = str(uuid.uuid4())
    deadline = asyncio.get_event_loop().time() + wait_timeout
    lock_key = _lock_key(session_id)

    while asyncio.get_event_loop().time() < deadline:
        acquired = await redis.set(lock_key, token, nx=True, ex=lock_ttl)
        if acquired:
            break
        await asyncio.sleep(0.05)
    else:
        raise TimeoutError(f"Could not acquire lock for session {session_id}")

    try:
        session = await load_session(session_id)
        yield session
        await save_session(session)
    finally:
        try:
            val = await redis.get(lock_key)
            if val == token:
                await redis.delete(lock_key)
        except Exception:
            pass


async def list_user_sessions(client_id: str) -> list[Session]:
    if not client_id:
        return []

    redis = await get_redis()
    key = _user_index_key(client_id)
    session_ids = await redis.zrevrange(key, 0, -1)
    sessions: list[Session] = []
    stale_ids: list[str] = []

    for session_id in session_ids:
        try:
            session = await load_session(session_id)
        except SessionNotFoundError:
            stale_ids.append(session_id)
            continue

        if client_id not in (session.role_owners or {}).values():
            stale_ids.append(session_id)
            continue

        sessions.append(session)

    if stale_ids:
        await redis.zrem(key, *stale_ids)

    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions
