"""Session storage abstraction with Redis/Memory fallback.

This module provides a unified interface for session persistence,
automatically falling back from Redis to in-memory storage on errors.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Generator, Optional

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger
from backend.domain.sessions.models import Session
from backend.infra.persistence.store_memory import (
    get_or_create_session as memory_get_or_create_session,
    list_user_sessions as memory_list_user_sessions,
    load_session as memory_load_session,
    save_session as memory_save_session,
    transactional_session as memory_transactional_session,
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

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

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

_redis_disabled = False  # pylint: disable=invalid-name
_init_logged = False  # pylint: disable=invalid-name


def _redis_allowed() -> bool:
    """Check if Redis backend is available and enabled."""
    backend = getattr(settings, "session_backend", "redis").lower()
    has_redis_url = bool(getattr(settings, "redis_url", None))
    return backend == "redis" and has_redis_url and not _redis_disabled


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError as exc:
        msg = str(exc)
        if "no running event loop" in msg or "no current event loop" in msg:
            # Safe to run coroutine from sync context
            return asyncio.run(coro)
        raise
    else:
        # Prevent accidental nested event loops
        raise RuntimeError("Synchronous store call inside running event loop")


def get_or_create_session(session_id: str, creator_user_id: Optional[str] = None) -> Session:
    """Get existing session or create a new one (sync)."""
    if _redis_allowed():
        try:
            return _run(redis_aget_or_create_session(session_id, user_id=creator_user_id))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis get_or_create failed, fallback to memory: %s", exc)
    return memory_get_or_create_session(session_id, user_id=creator_user_id)


def load_session(session_id: str) -> Session:
    """Load a session by ID (sync)."""
    if _redis_allowed():
        try:
            return _run(redis_aload_session(session_id))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis load failed, fallback to memory: %s", exc)
    return memory_load_session(session_id)


def save_session(session: Session, locked_by_caller: bool = False) -> None:  # noqa: ARG001
    """Save a session (sync)."""
    del locked_by_caller  # unused, kept for API compatibility
    if _redis_allowed():
        try:
            return _run(redis_asave_session(session))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis save failed, fallback to memory: %s", exc)
    return memory_save_session(session)


def transactional_session(session_id: str) -> Generator[Session, None, None]:
    """Context manager for transactional session access (sync)."""
    class _Ctx:
        """Sync context manager wrapper for async Redis operations."""

        def __init__(self) -> None:
            self._async_cm: "AbstractAsyncContextManager[Session] | None" = None
            self._memory_cm = None
            self._use_redis = False

        def __enter__(self) -> Session:
            if _redis_allowed():
                try:
                    self._async_cm = redis_atransactional_session(session_id)
                    self._use_redis = True
                    # pylint: disable-next=no-member
                    return _run(self._async_cm.__aenter__())  # type: ignore
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("Redis tx failed, fallback to memory: %s", exc)
                    self._use_redis = False

            # Use memory backend - store the context manager for proper cleanup
            self._memory_cm = memory_transactional_session(session_id)
            return self._memory_cm.__enter__()

        def __exit__(self, exc_type, exc, tb) -> bool:
            if self._use_redis and self._async_cm is not None:
                try:
                    # pylint: disable-next=no-member
                    result = self._async_cm.__aexit__(exc_type, exc, tb)
                    return _run(result)  # type: ignore
                except Exception as exit_exc:  # pylint: disable=broad-exception-caught
                    logger.error("Redis tx __exit__ failed: %s", exit_exc)
                    return False

            # Use the stored memory context manager for proper cleanup
            if self._memory_cm is not None:
                return self._memory_cm.__exit__(exc_type, exc, tb)
            return False

    return _Ctx()  # type: ignore[return-value]


def list_user_sessions(user_id: str) -> list[Session]:
    """List all sessions for a user (sync)."""
    if _redis_allowed():
        try:
            return _run(redis_alist_user_sessions(user_id))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis list_user_sessions failed, fallback to memory: %s", exc)
    return memory_list_user_sessions(user_id)


async def aget_or_create_session(session_id: str, user_id: Optional[str] = None) -> Session:
    """Get existing session or create a new one (async)."""
    if _redis_allowed():
        try:
            return await redis_aget_or_create_session(session_id, user_id=user_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis async get_or_create failed, fallback to memory: %s", exc)
    return await memory_aget_or_create_session(session_id, user_id=user_id)


async def aload_session(session_id: str) -> Session:
    """Load a session by ID (async)."""
    if _redis_allowed():
        try:
            return await redis_aload_session(session_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis async load failed, fallback to memory: %s", exc)
    return await memory_aload_session(session_id)


async def asave_session(session: Session, locked_by_caller: bool = False) -> None:  # noqa: ARG001
    """Save a session (async)."""
    del locked_by_caller  # unused, kept for API compatibility
    if _redis_allowed():
        try:
            await redis_asave_session(session)
            return
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis async save failed, fallback to memory: %s", exc)
    await memory_asave_session(session)


@asynccontextmanager
async def atransactional_session(session_id: str) -> AsyncIterator[Session]:
    """Async context manager for transactional session access."""
    if _redis_allowed():
        try:
            async with redis_atransactional_session(session_id) as session:
                yield session
            return
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis async transactional_session failed, fallback to memory: %s", exc)

    # pylint: disable-next=contextmanager-generator-missing-cleanup
    async with memory_atransactional_session(session_id) as session:
        yield session


async def alist_user_sessions(user_id: str) -> list[Session]:
    """List all sessions for a user (async)."""
    if _redis_allowed():
        try:
            return await redis_alist_user_sessions(user_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis async list_user_sessions failed, fallback to memory: %s", exc)
    return await memory_alist_user_sessions(user_id)


async def ainit_store() -> None:
    """Initialize the session store and log the active backend."""
    global _init_logged, _redis_disabled  # pylint: disable=global-statement
    if _init_logged:
        return
    if _redis_allowed():
        try:
            client = await get_redis()
            await client.ping()
            logger.info("Session backend: Redis (async)")
            _init_logged = True
            return
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Redis init failed, fallback to memory: %s", exc)
            _redis_disabled = True
    logger.info("Session backend: In-Memory (fallback)")
    _init_logged = True
