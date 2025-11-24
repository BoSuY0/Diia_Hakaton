from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Conversation:
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
        if session_id not in self._store:
            self._store[session_id] = Conversation(session_id=session_id)
        return self._store[session_id]


conversation_store = ConversationStore()
