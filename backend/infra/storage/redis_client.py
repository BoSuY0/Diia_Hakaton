"""Redis client accessor for async operations."""
from __future__ import annotations

from typing import Optional

from redis import asyncio as aioredis

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger

logger = get_logger(__name__)


class _RedisHolder:
    """Container for Redis client singleton."""

    client: Optional[aioredis.Redis] = None

    def get(self) -> Optional[aioredis.Redis]:
        """Get cached client."""
        return self.client

    def set(self, val: aioredis.Redis) -> None:
        """Set client."""
        self.client = val


_holder = _RedisHolder()


async def get_redis() -> aioredis.Redis:
    """Async Redis client accessor (cached)."""
    if _holder.client is not None:
        return _holder.client
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not set")
    _holder.client = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Using Redis client (redis.asyncio)")
    return _holder.client
