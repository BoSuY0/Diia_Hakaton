"""Redis-based conversation (LLM memory) persistence."""
from __future__ import annotations

import json
from typing import Any, Dict

from backend.infra.config.settings import settings
from backend.infra.storage.redis_client import get_redis
from backend.shared.logging import get_logger

logger = get_logger(__name__)

CONVERSATION_KEY_PREFIX = "conversation:"


def _conv_key(session_id: str) -> str:
    """Generate Redis key for conversation."""
    return f"{CONVERSATION_KEY_PREFIX}{session_id}"


def _conversation_to_dict(conv: "Conversation") -> Dict[str, Any]:
    """Serialize Conversation to dict for Redis storage."""
    return {
        "session_id": conv.session_id,
        "messages": conv.messages,
        "tags": conv.tags,
        "has_category_tool": conv.has_category_tool,
        "last_lang": conv.last_lang,
        "user_id": conv.user_id,
    }


def _dict_to_conversation(data: Dict[str, Any]) -> "Conversation":
    """Deserialize dict from Redis to Conversation."""
    from backend.api.http.state import Conversation
    
    return Conversation(
        session_id=data.get("session_id", ""),
        messages=data.get("messages", []),
        tags=data.get("tags", {}),
        has_category_tool=data.get("has_category_tool", False),
        last_lang=data.get("last_lang", "uk"),
        user_id=data.get("user_id"),
    )


async def aget_conversation(session_id: str) -> "Conversation":
    """Get or create a conversation from Redis.
    
    Returns existing conversation or creates a new empty one.
    """
    from backend.api.http.state import Conversation
    
    redis = await get_redis()
    key = _conv_key(session_id)
    
    raw = await redis.get(key)
    if raw is not None:
        try:
            data = json.loads(raw)
            return _dict_to_conversation(data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to parse conversation %s: %s", session_id, exc)
    
    # Create new conversation
    return Conversation(session_id=session_id)


async def asave_conversation(conv: "Conversation") -> None:
    """Save conversation to Redis with TTL."""
    redis = await get_redis()
    key = _conv_key(conv.session_id)
    
    data = _conversation_to_dict(conv)
    payload = json.dumps(data, ensure_ascii=False)
    
    ttl_seconds = max(settings.conversation_ttl_hours * 3600, 60)
    await redis.set(key, payload, ex=ttl_seconds)


async def areset_conversation(session_id: str) -> "Conversation":
    """Reset conversation history, returns new empty conversation."""
    from backend.api.http.state import Conversation
    
    redis = await get_redis()
    key = _conv_key(session_id)
    
    # Delete existing
    await redis.delete(key)
    
    # Create and save new empty conversation
    conv = Conversation(session_id=session_id)
    await asave_conversation(conv)
    return conv


async def aremove_conversation(session_id: str) -> None:
    """Remove conversation from Redis."""
    redis = await get_redis()
    key = _conv_key(session_id)
    await redis.delete(key)
