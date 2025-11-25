"""Session storage abstraction with Redis/Memory fallback.

This module provides a unified interface for session persistence,
automatically falling back from Redis to in-memory storage on errors.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Generator, Optional

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger
from backend.domain.sessions.models import Session
from backend.infra.persistence.store_memory import (
    get_or_create_session as memory_get_or_create_session,
    list_user_sessions as memory_list_user_sessions,
    load_session as memory_load_session,
    save_session as memory_save_session,
    aget_or_create_session as memory_aget_or_create_session,
    alist_user_sessions as memory_alist_user_sessions,
    aload_session as memory_aload_session,
    asave_session as memory_asave_session,
    atransactional_session as memory_atransactional_session,
)
from backend.infra.persistence.store_redis import (
    get_or_create_session as redis_aget_or_create_session,
    list_user_sessions as redis_alist_user_sessions,
    load_session as redis_aload_session,
    save_session as redis_asave_session,
    transactional_session as redis_atransactional_session,
)
from backend.infra.persistence.store_utils import generate_readable_id
from backend.infra.storage.redis_client import get_redis

# Re-export for backward compatibility
__all__ = [
    "generate_readable_id",
    "get_or_create_session",
    "load_session",
    "save_session",
    "transactional_session",
    "list_user_sessions",
    "aget_or_create_session",
    "aload_session",
    "asave_session",
    "atransactional_session",
    "alist_user_sessions",
    "ainit_store",
]

logger = get_logger(__name__)

# Local locks for sync transactional access
_sync_locks: dict[str, threading.RLock] = {}
_sync_global_lock = threading.RLock()


def _get_sync_lock(session_id: str) -> threading.RLock:
    """Get or create a local lock for synchronous transactional access."""
    with _sync_global_lock:
        lock = _sync_locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _sync_locks[session_id] = lock
        return lock


class _StoreState:
    """
    Module-level store state container.

    Tracks Redis availability and initialization status.
    """

    redis_disabled: bool = False
    init_logged: bool = False

    def reset(self) -> None:
        """Reset state for testing."""
        self.redis_disabled = False
        self.init_logged = False

    def is_redis_available(self) -> bool:
        """Check if Redis is available."""
        return not self.redis_disabled


_state = _StoreState()


def _redis_allowed() -> bool:
    """Check if Redis backend is available and enabled."""
    backend = getattr(settings, "session_backend", "redis").lower()
    has_redis_url = bool(getattr(settings, "redis_url", None))
    return backend == "redis" and has_redis_url and not _state.redis_disabled


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError as exc:
        msg = str(exc)
        if "no running event loop" in msg or "no current event loop" in msg:
            # Safe to run coroutine from sync context
            return asyncio.run(coro)
        raise
    # Prevent accidental nested event loops
    raise RuntimeError("Synchronous store call inside running event loop")


def get_or_create_session(session_id: str, creator_user_id: Optional[str] = None) -> Session:
    """Get existing session or create a new one (sync)."""
    if _redis_allowed():
        try:
            return _run(redis_aget_or_create_session(session_id, user_id=creator_user_id))
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis get_or_create failed, fallback to memory: %s", exc)
    return memory_get_or_create_session(session_id, user_id=creator_user_id)


def load_session(session_id: str) -> Session:
    """Load a session by ID (sync)."""
    if _redis_allowed():
        try:
            return _run(redis_aload_session(session_id))
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis load failed, fallback to memory: %s", exc)
    return memory_load_session(session_id)


def save_session(session: Session, _locked_by_caller: bool = False) -> None:
    """Save a session (sync). _locked_by_caller is unused, kept for API compat."""
    if _redis_allowed():
        try:
            return _run(redis_asave_session(session))
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis save failed, fallback to memory: %s", exc)
    return memory_save_session(session)


@contextmanager
def transactional_session(session_id: str) -> Generator[Session, None, None]:
    """Context manager for transactional session access (sync).

    Uses Redis if available, falls back to memory on connection errors.
    Load and save operations use the unified store functions with fallback.
    Local locking ensures atomicity within the same process.
    """
    lock = _get_sync_lock(session_id)
    with lock:
        # Use the unified load/save functions which have Redis fallback built-in
        session = load_session(session_id)
        try:
            yield session
        finally:
            save_session(session)


def list_user_sessions(user_id: str) -> list[Session]:
    """List all sessions for a user (sync)."""
    if _redis_allowed():
        try:
            return _run(redis_alist_user_sessions(user_id))
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis list_user_sessions failed, fallback to memory: %s", exc)
    return memory_list_user_sessions(user_id)


async def aget_or_create_session(session_id: str, user_id: Optional[str] = None) -> Session:
    """Get existing session or create a new one (async)."""
    if _redis_allowed():
        try:
            return await redis_aget_or_create_session(session_id, user_id=user_id)
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis async get_or_create failed, fallback to memory: %s", exc)
    return await memory_aget_or_create_session(session_id, user_id=user_id)


async def aload_session(session_id: str) -> Session:
    """Load a session by ID (async)."""
    if _redis_allowed():
        try:
            return await redis_aload_session(session_id)
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis async load failed, fallback to memory: %s", exc)
    return await memory_aload_session(session_id)


async def asave_session(session: Session, _locked_by_caller: bool = False) -> None:
    """Save a session (async). _locked_by_caller is unused, kept for API compat."""
    if _redis_allowed():
        try:
            await redis_asave_session(session)
            return
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis async save failed, fallback to memory: %s", exc)
    await memory_asave_session(session)


@asynccontextmanager
async def atransactional_session(session_id: str):
    """Async context manager for transactional session access with fallback.

    Tries Redis first, falls back to memory on connection errors.
    Usage: async with atransactional_session(sid) as session: ...
    """
    use_redis = _redis_allowed()

    if use_redis:
        # Check Redis connectivity before entering context
        try:
            client = await get_redis()
            await client.ping()
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error(
                "Redis ping failed before transactional_session, fallback to memory: %s", exc
            )
            use_redis = False

    if use_redis:
        ctx = redis_atransactional_session(session_id)
    else:
        ctx = memory_atransactional_session(session_id)
    async with ctx as session:
        yield session


async def alist_user_sessions(user_id: str) -> list[Session]:
    """List all sessions for a user (async)."""
    if _redis_allowed():
        try:
            return await redis_alist_user_sessions(user_id)
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis async list_user_sessions failed, fallback to memory: %s", exc)
    return await memory_alist_user_sessions(user_id)


async def ainit_store() -> None:
    """Initialize the session store and log the active backend."""
    if _state.init_logged:
        return
    if _redis_allowed():
        try:
            client = await get_redis()
            await client.ping()
            logger.info("Session backend: Redis (async)")
            _state.init_logged = True
            return
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
            logger.error("Redis init failed, fallback to memory: %s", exc)
            _state.redis_disabled = True
    logger.info("Session backend: In-Memory (fallback)")
    _state.init_logged = True
