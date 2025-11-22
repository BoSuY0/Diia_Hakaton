from __future__ import annotations

import redis

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

_redis = None


def get_redis():
    """
    Returns a cached Redis client instance.
    """
    global _redis
    if _redis is not None:
        return _redis

    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not set")
    _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Using Redis client (redis-py)")
    return _redis
