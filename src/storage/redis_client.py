from __future__ import annotations

import asyncio
import threading
from typing import Any

import redis

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

_redis = None


class GlideClientWrapper:
    """
    Запускає GlideClusterClient в окремому event loop і надає синхронний API,
    сумісний з використаними в коді методами redis-py.
    """

    def __init__(self, config: GlideClusterClientConfiguration) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        fut = asyncio.run_coroutine_threadsafe(GlideClusterClient.create(config), self._loop)
        self._client: GlideClusterClient = fut.result(timeout=10)

    def _run(self, coro) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=10)

    def set(self, key: str, value: str, ex: int | None = None) -> Any:
        return self._run(self._client.set(key, value, ex=ex))

    def get(self, key: str) -> Any:
        res = self._run(self._client.get(key))
        if isinstance(res, bytes):
            return res.decode("utf-8")
        return res

    def delete(self, key: str) -> Any:
        return self._run(self._client.del_(key))

    def zadd(self, key: str, mapping: dict[str, float]) -> Any:
        return self._run(self._client.zadd(key, mapping))

    def zrevrange(self, key: str, start: int, stop: int) -> list[str]:
        res = self._run(self._client.zrevrange(key, start, stop))
        return [v.decode("utf-8") if isinstance(v, bytes) else v for v in res]

    def zrem(self, key: str, *members: str) -> Any:
        return self._run(self._client.zrem(key, *members))

    def ttl(self, key: str) -> int:
        return self._run(self._client.ttl(key))

    def ping(self) -> Any:
        return self._run(self._client.ping())

    def close(self) -> None:
        try:
            self._run(self._client.close())
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
        except Exception:
            pass


def _build_glide_client() -> GlideClientWrapper:
    try:
        from glide import GlideClusterClient, GlideClusterClientConfiguration, NodeAddress
    except Exception as exc:
        raise RuntimeError(f"glide client not available: {exc}") from exc

    if not settings.valkey_addresses:
        raise RuntimeError("VALKEY_ADDRESSES is not set")
    addresses = [NodeAddress(host, port) for host, port in settings.valkey_addresses]
    config = GlideClusterClientConfiguration(addresses=addresses, use_tls=settings.valkey_use_tls)
    return GlideClientWrapper(config)


def get_redis():
    """
    Returns a cached Redis-like client instance (redis-py or Valkey Glide wrapper).
    """
    global _redis
    if _redis is not None:
        return _redis

    if settings.valkey_use_glide:
        try:
            _redis = _build_glide_client()
            logger.info("Using Valkey Glide client")
            return _redis
        except Exception as exc:
            logger.error("Failed to initialize Valkey Glide client: %s", exc)

    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not set")
    
    # Determine if SSL/TLS is needed based on URL scheme
    use_ssl = settings.redis_url.startswith("rediss://")
    
    # Build connection parameters
    connection_kwargs = {
        "decode_responses": True,
        "socket_connect_timeout": 5,
        "socket_keepalive": True,
        "health_check_interval": 30
    }
    
    # Add SSL parameters only for secure connections
    if use_ssl:
        connection_kwargs["ssl_cert_reqs"] = None  # Accept AWS certificates
        logger.info("Using standard Redis client (with SSL/TLS support)")
    else:
        logger.info("Using standard Redis client (non-SSL)")
    
    _redis = redis.Redis.from_url(settings.redis_url, **connection_kwargs)
    return _redis
