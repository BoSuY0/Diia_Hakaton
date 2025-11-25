"""Redis-based session persistence with distributed locking."""
from __future__ import annotations

import json
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from backend.domain.sessions.ttl import ttl_hours_for_session
from backend.shared.errors import SessionNotFoundError
from backend.domain.documents.user_document import save_user_document_async
from backend.domain.sessions.models import Session
from backend.infra.persistence.store_utils import _from_dict, session_to_dict
from backend.infra.storage.redis_client import get_redis
from backend.shared.logging import get_logger

logger = get_logger(__name__)

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
    """Save session to Redis with TTL and update user indexes."""
    redis = await get_redis()
    session.updated_at = datetime.now(timezone.utc)

    data = session_to_dict(session)
    payload = json.dumps(data, ensure_ascii=False)
    ttl_seconds = max(ttl_hours_for_session(session) * 3600, 1)
    await redis.set(_session_key(session.session_id), payload, ex=ttl_seconds)

    participants = set((session.role_owners or {}).values())
    if session.creator_user_id:
        participants.add(session.creator_user_id)
    if participants:
        ts = session.updated_at.timestamp()
        mapping = {session.session_id: ts}
        for uid in participants:
            if uid:
                await redis.zadd(_user_index_key(uid), mapping)

    try:
        await save_user_document_async(session)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("Failed to save user document for session %s: %s", session.session_id, exc)


async def load_session(session_id: str) -> Session:
    """Load session from Redis by ID."""
    redis = await get_redis()
    raw = await redis.get(_session_key(session_id))
    if raw is None:
        raise SessionNotFoundError(f"Session '{session_id}' not found")
    data = json.loads(raw)
    return _from_dict(data)


async def get_or_create_session(session_id: str, user_id: str | None = None) -> Session:
    """Get existing session or create a new one."""
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
) -> AsyncIterator[Session]:
    """Async context manager for transactional session access with locking."""
    redis = await get_redis()
    token = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_timeout
    lock_key = _lock_key(session_id)

    while loop.time() < deadline:
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
            # Redis returns bytes, token is str - decode for comparison
            if val is not None:
                val_str = val.decode("utf-8") if isinstance(val, bytes) else val
                if val_str == token:
                    await redis.delete(lock_key)
        except (ConnectionError, TimeoutError, OSError):
            pass  # Lock cleanup is best-effort


async def list_user_sessions(user_id: str) -> list[Session]:
    """List all sessions for a user, cleaning up stale entries."""
    if not user_id:
        return []

    redis = await get_redis()
    key = _user_index_key(user_id)
    session_ids = await redis.zrevrange(key, 0, -1)
    sessions: list[Session] = []
    stale_ids: list[str] = []

    for raw_session_id in session_ids:
        # Redis may return bytes, decode if needed
        session_id = raw_session_id.decode("utf-8") if isinstance(raw_session_id, bytes) else raw_session_id
        try:
            session = await load_session(session_id)
        except SessionNotFoundError:
            stale_ids.append(session_id)
            continue

        role_owners = (session.role_owners or {}).values()
        if user_id not in role_owners and user_id != session.creator_user_id:
            stale_ids.append(session_id)
            continue

        sessions.append(session)

    if stale_ids:
        await redis.zrem(key, *stale_ids)

    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions
