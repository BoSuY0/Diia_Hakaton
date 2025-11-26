"""Conversation state management for HTTP API.

Supports both in-memory and Redis-backed storage for LLM conversation history.
Redis is used when available, with automatic fallback to in-memory storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Conversation:
    """Represents a conversation state with messages and PII tags."""

    session_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    # Мапа тегів PII → сире значення (накопичується за всю сесію)
    tags: Dict[str, str] = field(default_factory=dict)
    # Чи вже був set_category у поточній розмові (для state-gating, незалежно від pruning)
    has_category_tool: bool = False
    # Остання мова користувача для серверних відповідей ("uk" або "en")
    last_lang: str = "uk"
    # Поточний user_id (для передачі у тулли)
    user_id: str | None = None


class _ConversationStoreState:
    """Module-level state for conversation store."""

    redis_disabled: bool = False
    init_logged: bool = False

    def reset(self) -> None:
        """Reset state for testing."""
        self.redis_disabled = False
        self.init_logged = False


_state = _ConversationStoreState()


def _redis_allowed() -> bool:
    """Check if Redis backend is available and enabled."""
    backend = getattr(settings, "session_backend", "redis").lower()
    has_redis_url = bool(getattr(settings, "redis_url", None))
    return backend == "redis" and has_redis_url and not _state.redis_disabled


class ConversationStore:
    """
    Conversation history storage with Redis/Memory fallback.

    Uses Redis when available for persistence across server restarts.
    Falls back to in-memory storage on Redis errors.
    """

    def __init__(self) -> None:
        self._memory_store: Dict[str, Conversation] = {}

    # ──────────────────────────────────────────────────────────────────
    # Synchronous API (for backward compatibility)
    # ──────────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> Conversation:
        """Get or create a conversation for the given session ID (sync).
        
        Note: For Redis-backed storage, use aget() in async context.
        This sync method only uses in-memory cache.
        """
        if session_id not in self._memory_store:
            self._memory_store[session_id] = Conversation(session_id=session_id)
        return self._memory_store[session_id]

    def remove(self, session_id: str) -> None:
        """Remove a conversation from memory store (sync)."""
        self._memory_store.pop(session_id, None)

    def reset(self, session_id: str) -> None:
        """Reset conversation history in memory (sync)."""
        self._memory_store[session_id] = Conversation(session_id=session_id)

    # ──────────────────────────────────────────────────────────────────
    # Async API (with Redis support)
    # ──────────────────────────────────────────────────────────────────

    async def aget(self, session_id: str) -> Conversation:
        """Get or create a conversation (async, Redis-backed)."""
        if _redis_allowed():
            try:
                from backend.infra.persistence.conversation_store_redis import (
                    aget_conversation,
                )

                conv = await aget_conversation(session_id)
                # Update memory cache
                self._memory_store[session_id] = conv
                return conv
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
                logger.warning("Redis conversation get failed, using memory: %s", exc)

        # Fallback to memory
        return self.get(session_id)

    async def asave(self, conv: Conversation) -> None:
        """Save conversation (async, to Redis if available)."""
        # Always update memory cache
        self._memory_store[conv.session_id] = conv

        if _redis_allowed():
            try:
                from backend.infra.persistence.conversation_store_redis import (
                    asave_conversation,
                )

                await asave_conversation(conv)
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
                logger.warning("Redis conversation save failed: %s", exc)

    async def areset(self, session_id: str) -> Conversation:
        """Reset conversation history (async, Redis-backed).
        
        Returns new empty conversation.
        """
        if _redis_allowed():
            try:
                from backend.infra.persistence.conversation_store_redis import (
                    areset_conversation,
                )

                conv = await areset_conversation(session_id)
                self._memory_store[session_id] = conv
                return conv
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
                logger.warning("Redis conversation reset failed, using memory: %s", exc)

        # Fallback to memory
        self.reset(session_id)
        return self._memory_store[session_id]

    async def aremove(self, session_id: str) -> None:
        """Remove conversation (async, from Redis if available)."""
        self._memory_store.pop(session_id, None)

        if _redis_allowed():
            try:
                from backend.infra.persistence.conversation_store_redis import (
                    aremove_conversation,
                )

                await aremove_conversation(session_id)
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
                logger.warning("Redis conversation remove failed: %s", exc)


conversation_store = ConversationStore()
