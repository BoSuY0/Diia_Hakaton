from __future__ import annotations

import asyncio
from typing import Optional

from redis import asyncio as aioredis

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger

logger = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """
    Async Redis client accessor (cached).
    """
    global _redis
    if _redis is not None:
        return _redis
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not set")
    _redis = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Using Redis client (redis.asyncio)")
    return _redis
