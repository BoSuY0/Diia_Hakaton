from __future__ import annotations

import asyncio
from typing import Generator, Optional

from contextlib import asynccontextmanager

from src.common.config import settings
from src.common.logging import get_logger
from src.sessions.models import Session
from src.sessions.store_memory import (
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
from src.sessions.store_redis import (
    get_or_create_session as redis_aget_or_create_session,
    list_user_sessions as redis_alist_user_sessions,
    load_session as redis_aload_session,
    save_session as redis_asave_session,
    transactional_session as redis_atransactional_session,
)
from src.sessions.store_utils import generate_readable_id
from src.common.async_utils import run_sync
from src.storage.redis_client import get_redis

logger = get_logger(__name__)

_redis_disabled = False
_REDIS_FAIL = object()
_init_logged = False


def _redis_allowed() -> bool:
    backend = getattr(settings, "session_backend", "redis").lower()
    has_redis_url = bool(getattr(settings, "redis_url", None))
    return backend == "redis" and has_redis_url and not _redis_disabled


def _run(coro):
    try:
        asyncio.get_running_loop()
        raise RuntimeError("Synchronous store call inside running event loop")
    except RuntimeError as exc:
        if "loop" in str(exc):
            # No running loop -> run normally
            return asyncio.run(coro)
        raise


def _with_redis(func, *args, **kwargs):
    global _redis_disabled
    if not _redis_allowed():
        return _REDIS_FAIL
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        logger.error("Redis backend unavailable, falling back to in-memory: %s", exc)
        _redis_disabled = True
        return _REDIS_FAIL


async def _with_redis_async(func, *args, **kwargs):
    global _redis_disabled
    if not _redis_allowed():
        return _REDIS_FAIL
    try:
        return await run_sync(func, *args, **kwargs)
    except Exception as exc:
        logger.error("Redis backend unavailable, falling back to in-memory: %s", exc)
        _redis_disabled = True
        return _REDIS_FAIL


def get_or_create_session(session_id: str, user_id: Optional[str] = None) -> Session:
    if _redis_allowed():
        try:
            return _run(redis_aget_or_create_session(session_id, user_id=user_id))
        except Exception as exc:
            logger.error("Redis get_or_create failed, fallback to memory: %s", exc)
    return memory_get_or_create_session(session_id, user_id=user_id)


def load_session(session_id: str) -> Session:
    if _redis_allowed():
        try:
            return _run(redis_aload_session(session_id))
        except Exception as exc:
            logger.error("Redis load failed, fallback to memory: %s", exc)
    return memory_load_session(session_id)


def save_session(session: Session, locked_by_caller: bool = False) -> None:
    if _redis_allowed():
        try:
            return _run(redis_asave_session(session))
        except Exception as exc:
            logger.error("Redis save failed, fallback to memory: %s", exc)
    return memory_save_session(session)


def transactional_session(session_id: str) -> Generator[Session, None, None]:
    # Sync context manager via async backend; fallback to memory on errors
    class _Ctx:
        def __enter__(self):
            if _redis_allowed():
                try:
                    self._async_cm = redis_atransactional_session(session_id)
                    self._manager = _run(self._async_cm.__aenter__())
                    return self._manager
                except Exception as exc:
                    logger.error("Redis tx failed, fallback to memory: %s", exc)
            self._manager = memory_transactional_session(session_id).__enter__()
            return self._manager

        def __exit__(self, exc_type, exc, tb):
            if _redis_allowed():
                try:
                    if hasattr(self, "_async_cm"):
                        return _run(self._async_cm.__aexit__(exc_type, exc, tb))
                except Exception:
                    pass
            return memory_transactional_session(session_id).__exit__(exc_type, exc, tb)
    return _Ctx()


def list_user_sessions(client_id: str) -> list[Session]:
    if _redis_allowed():
        try:
            return _run(redis_alist_user_sessions(client_id))
        except Exception as exc:
            logger.error("Redis list_user_sessions failed, fallback to memory: %s", exc)
    return memory_list_user_sessions(client_id)


async def aget_or_create_session(session_id: str, user_id: Optional[str] = None) -> Session:
    if _redis_allowed():
        try:
            return await redis_aget_or_create_session(session_id, user_id=user_id)
        except Exception as exc:
            logger.error("Redis async get_or_create failed, fallback to memory: %s", exc)
    return await memory_aget_or_create_session(session_id, user_id=user_id)


async def aload_session(session_id: str) -> Session:
    if _redis_allowed():
        try:
            return await redis_aload_session(session_id)
        except Exception as exc:
            logger.error("Redis async load failed, fallback to memory: %s", exc)
    return await memory_aload_session(session_id)


async def asave_session(session: Session, locked_by_caller: bool = False) -> None:
    if _redis_allowed():
        try:
            await redis_asave_session(session)
            return
        except Exception as exc:
            logger.error("Redis async save failed, fallback to memory: %s", exc)
    await memory_asave_session(session)


@asynccontextmanager
async def atransactional_session(session_id: str):
    """
    Async context manager for transactional session access.
    Uses Redis when available, otherwise in-memory async locks.
    """
    if _redis_allowed():
        try:
            async with redis_atransactional_session(session_id) as session:
                yield session
            return
        except Exception as exc:
            logger.error("Redis async transactional_session failed, fallback to memory: %s", exc)

    async with memory_atransactional_session(session_id) as session:
        yield session


async def alist_user_sessions(client_id: str) -> list[Session]:
    if _redis_allowed():
        try:
            return await redis_alist_user_sessions(client_id)
        except Exception as exc:
            logger.error("Redis async list_user_sessions failed, fallback to memory: %s", exc)
    return await memory_alist_user_sessions(client_id)


async def ainit_store() -> None:
    global _init_logged, _redis_disabled
    if _init_logged:
        return
    if _redis_allowed():
        try:
            client = await get_redis()
            await client.ping()
            logger.info("Session backend: Redis (async)")
            _init_logged = True
            return
        except Exception as exc:
            logger.error("Redis init failed, fallback to memory: %s", exc)
            _redis_disabled = True
    logger.info("Session backend: In-Memory (fallback)")
    _init_logged = True


def init_store() -> None:
    """
    Виконує одноразову ініціалізацію стореджу сесій та логування бекенду.
    """
    global _init_logged, _redis_disabled
    if _init_logged:
        return

    if _redis_allowed():
        try:
            # Проста перевірка доступності
            from src.storage.redis_client import get_redis

            client = get_redis()
            try:
                client.ping()
            except Exception:
                # Якщо ping не підтримується (in-memory фейковий) — просто продовжуємо
                pass
            logger.info("Session backend: Redis (primary)")
            _init_logged = True
            return
        except Exception as exc:
            logger.error("Redis session backend unavailable, switching to in-memory: %s", exc)
            _redis_disabled = True

    logger.info("Session backend: In-Memory (fallback)")
    _init_logged = True
