from __future__ import annotations

from typing import Generator, Optional

from src.common.config import settings
from src.common.logging import get_logger
from src.sessions.models import Session
from src.sessions.store_memory import (
    get_or_create_session as memory_get_or_create_session,
    list_user_sessions as memory_list_user_sessions,
    load_session as memory_load_session,
    save_session as memory_save_session,
    transactional_session as memory_transactional_session,
)
from src.sessions.store_redis import (
    get_or_create_session as redis_get_or_create_session,
    list_user_sessions as redis_list_user_sessions,
    load_session as redis_load_session,
    save_session as redis_save_session,
    transactional_session as redis_transactional_session,
)
from src.sessions.store_utils import generate_readable_id

logger = get_logger(__name__)

_redis_disabled = False
_REDIS_FAIL = object()
_init_logged = False


def _redis_allowed() -> bool:
    backend = getattr(settings, "session_backend", "redis").lower()
    has_redis_url = bool(getattr(settings, "redis_url", None))
    use_glide = getattr(settings, "valkey_use_glide", False)
    return backend == "redis" and (has_redis_url or use_glide) and not _redis_disabled


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


def get_or_create_session(session_id: str, user_id: Optional[str] = None) -> Session:
    result = _with_redis(redis_get_or_create_session, session_id, user_id=user_id)
    if result is not _REDIS_FAIL:
        return result
    return memory_get_or_create_session(session_id, user_id=user_id)


def load_session(session_id: str) -> Session:
    result = _with_redis(redis_load_session, session_id)
    if result is not _REDIS_FAIL:
        return result
    return memory_load_session(session_id)


def save_session(session: Session, locked_by_caller: bool = False) -> None:
    result = _with_redis(redis_save_session, session)
    if result is not _REDIS_FAIL:
        return result
    return memory_save_session(session)


def transactional_session(session_id: str) -> Generator[Session, None, None]:
    result = _with_redis(redis_transactional_session, session_id)
    if result is not _REDIS_FAIL:
        return result
    return memory_transactional_session(session_id)


def list_user_sessions(client_id: str) -> list[Session]:
    result = _with_redis(redis_list_user_sessions, client_id)
    if result is not _REDIS_FAIL:
        return result
    return memory_list_user_sessions(client_id)


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
