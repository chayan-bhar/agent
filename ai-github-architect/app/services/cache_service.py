"""
Redis Cache Service.

Provides a clean async interface for caching GitHub API responses and
expensive LLM structured outputs.

Key responsibilities:
- GitHub API response caching (default TTL: 1 hour) — avoids rate limits
- LLM structured output caching (default TTL: 24 hours) — reduces cost
- Analysis status caching (short TTL: 30 seconds) — reduces DB reads

All cache misses degrade gracefully — the cache is never on the critical path.
If Redis is unavailable, the application continues without caching.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Default TTLs (seconds)
TTL_GITHUB_API = 3600       # 1 hour — repo metadata, file trees
TTL_LLM_OUTPUT = 86400      # 24 hours — expensive LLM calls
TTL_ANALYSIS_STATUS = 30    # 30 seconds — status polling cache


class CacheService:
    """
    Async Redis cache service with graceful degradation.

    All methods catch RedisError and return None/False on failure
    rather than raising — the cache is always optional.
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    @classmethod
    async def create(cls) -> "CacheService":
        """Create a CacheService connected to Redis from settings."""
        settings = get_settings()
        client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            retry_on_timeout=True,
        )
        instance = cls(client)
        await instance._ping()
        return instance

    async def _ping(self) -> bool:
        """Check Redis connectivity. Logs warning on failure, does not raise."""
        try:
            await self._client.ping()
            logger.info("redis_connected", url=_mask_redis_url(get_settings().redis_url))
            return True
        except RedisError as exc:
            logger.warning(
                "redis_unavailable",
                error=str(exc),
                message="Cache disabled — Redis not reachable",
            )
            return False

    async def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a cached value by key.

        Returns:
            Deserialized Python object, or None if not found / Redis error.
        """
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            value = json.loads(raw)
            logger.debug("cache_hit", key=_short_key(key))
            return value
        except RedisError as exc:
            logger.warning("cache_get_error", key=_short_key(key), error=str(exc))
            return None
        except json.JSONDecodeError as exc:
            logger.warning("cache_decode_error", key=_short_key(key), error=str(exc))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int = TTL_GITHUB_API,
    ) -> bool:
        """
        Store a value in cache with TTL.

        Args:
            key: Cache key.
            value: JSON-serializable value.
            ttl: Time-to-live in seconds.

        Returns:
            True on success, False on error.
        """
        try:
            raw = json.dumps(value, default=str)
            await self._client.setex(key, ttl, raw)
            logger.debug("cache_set", key=_short_key(key), ttl=ttl)
            return True
        except RedisError as exc:
            logger.warning("cache_set_error", key=_short_key(key), error=str(exc))
            return False
        except (TypeError, ValueError) as exc:
            logger.warning("cache_serialize_error", key=_short_key(key), error=str(exc))
            return False

    async def delete(self, key: str) -> bool:
        """Remove a key from cache."""
        try:
            await self._client.delete(key)
            return True
        except RedisError as exc:
            logger.warning("cache_delete_error", key=_short_key(key), error=str(exc))
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Useful for invalidating all cached data for a specific repository.

        Returns:
            Number of keys deleted.
        """
        try:
            keys = await self._client.keys(pattern)
            if not keys:
                return 0
            deleted = await self._client.delete(*keys)
            logger.info("cache_pattern_deleted", pattern=pattern, count=deleted)
            return deleted
        except RedisError as exc:
            logger.warning("cache_pattern_delete_error", pattern=pattern, error=str(exc))
            return 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        try:
            return bool(await self._client.exists(key))
        except RedisError:
            return False

    async def get_or_set(
        self,
        key: str,
        factory,
        ttl: int = TTL_GITHUB_API,
    ) -> Any:
        """
        Return cached value or compute and cache it.

        Args:
            key: Cache key.
            factory: Async callable returning the value to cache.
            ttl: Time-to-live in seconds.

        Returns:
            Cached or freshly computed value.
        """
        cached = await self.get(key)
        if cached is not None:
            return cached

        value = await factory()
        await self.set(key, value, ttl=ttl)
        return value

    async def close(self) -> None:
        """Close the Redis connection."""
        try:
            await self._client.aclose()
            logger.info("redis_connection_closed")
        except RedisError:
            pass


# ── Module-level singleton ────────────────────────────────────────────────────

_cache_service: Optional[CacheService] = None


async def get_cache_service() -> Optional[CacheService]:
    """
    Return the shared CacheService singleton, or None if Redis is unavailable.

    This function is safe to call even if Redis is not configured — it
    returns None and all callers must handle the None case.
    """
    global _cache_service
    if _cache_service is None:
        try:
            _cache_service = await CacheService.create()
        except Exception as exc:
            logger.warning(
                "cache_service_init_failed",
                error=str(exc),
                message="Continuing without cache",
            )
            return None
    return _cache_service


async def close_cache_service() -> None:
    """Shut down the cache service (call at application shutdown)."""
    global _cache_service
    if _cache_service:
        await _cache_service.close()
        _cache_service = None


# ── Cache key builders ────────────────────────────────────────────────────────


def github_key(owner: str, repo: str, resource: str) -> str:
    """Build a cache key for a GitHub API resource."""
    return f"gh:{owner}/{repo}:{resource}"


def analysis_status_key(analysis_id: str) -> str:
    """Build a cache key for an analysis status."""
    return f"analysis:status:{analysis_id}"


def repo_pattern(owner: str, repo: str) -> str:
    """Pattern to match all cache keys for a repository."""
    return f"gh:{owner}/{repo}:*"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mask_redis_url(url: str) -> str:
    """Mask password in Redis URL for safe logging."""
    try:
        if "@" in url:
            scheme, rest = url.split("://", 1)
            auth, host = rest.rsplit("@", 1)
            return f"{scheme}://****@{host}"
    except Exception:
        pass
    return url


def _short_key(key: str) -> str:
    """Truncate long keys for readable log output."""
    return key[:60] + "…" if len(key) > 60 else key
