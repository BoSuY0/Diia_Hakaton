"""Conversation state management for HTTP API."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


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


class ConversationStore:
    """
    In-memory conversation history per session.

    For production, replace with persistent storage (Redis/DB).
    """

    def __init__(self) -> None:
        self._store: Dict[str, Conversation] = {}

    def get(self, session_id: str) -> Conversation:
        """Get or create a conversation for the given session ID."""
        if session_id not in self._store:
            self._store[session_id] = Conversation(session_id=session_id)
        return self._store[session_id]


    def remove(self, session_id: str) -> None:
        """Remove a conversation from the store."""
        self._store.pop(session_id, None)

    def reset(self, session_id: str) -> None:
        """Reset conversation history for the given session ID.
        
        Creates a new empty Conversation, effectively starting a fresh chat
        while keeping the same session_id binding.
        """
        self._store[session_id] = Conversation(session_id=session_id)


conversation_store = ConversationStore()
