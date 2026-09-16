"""
rate_limiter.py — Sliding window rate limiter for the Jessica endpoints.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import structlog
from cachetools import TTLCache

from config import REDIS_URL, USER_RATE_LIMIT_PER_MINUTE

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Rate limiter — Redis sliding window with in-process TTLCache fallback
# ══════════════════════════════════════════════════════════════════════════════

class _RedisRateLimiter:
    """
    Sliding-window rate limiter backed by Redis sorted sets.
    Safe across multiple replicas/workers.

    Each user gets a sorted-set key  ratelimit:<uid>  whose members are
    request timestamps (score = epoch seconds, member = uuid4 for uniqueness).
    On each call we:
      1. Remove members older than 60 s (ZREMRANGEBYSCORE)
      2. Count remaining members (ZCARD)
      3. If count < max, add the new timestamp and set a 61 s TTL
    All three steps run atomically via a Lua script.
    """

    _LUA_SCRIPT = """
local key     = KEYS[1]
local now     = tonumber(ARGV[1])
local window  = tonumber(ARGV[2])
local limit   = tonumber(ARGV[3])
local member  = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window + 1)
return 1
"""

    def __init__(self, redis_url: str, max_per_minute: int) -> None:
        import redis.asyncio as aioredis
        self._client  = aioredis.from_url(redis_url, decode_responses=True)
        self._max     = max_per_minute
        self._script: str | None = None          # SHA after first SCRIPT LOAD
        self._ready   = False

    async def _ensure_script(self) -> None:
        if self._script is None:
            self._script = await self._client.script_load(self._LUA_SCRIPT)
        self._ready = True

    async def is_allowed(self, uid: str) -> bool:
        try:
            await self._ensure_script()
            key    = f"ratelimit:{uid}"
            now    = time.time()
            member = uuid.uuid4().hex
            result = await self._client.evalsha(
                self._script, 1, key, now, 60, self._max, member
            )
            return bool(result)
        except Exception as exc:
            # Redis down → fail open (log + allow the request)
            logger.warning("rate_limiter.redis_error", error=str(exc))
            return True

    async def close(self) -> None:
        await self._client.aclose()


class _InProcessRateLimiter:
    """
    Sliding-window rate limiter using a TTLCache for per-user timestamp lists.
    Safe for single-process deployments only.

    TTLCache evicts entries after `ttl` seconds of no access, preventing
    the unbounded memory growth of the original defaultdict approach.
    Per-user asyncio.Lock eliminates the global-lock bottleneck.
    """

    def __init__(self, max_per_minute: int, cache_maxsize: int = 4096) -> None:
        self._max   = max_per_minute
        # TTLCache: entries auto-evict after 120 s of no access (2 × window)
        self._cache: TTLCache = TTLCache(maxsize=cache_maxsize, ttl=120)
        # MED-05: use a TTLCache (not a plain dict) for per-user locks too.
        # The old `dict[str, asyncio.Lock]` never evicted, so every unique user
        # id that ever hit the endpoint left a permanent entry — a slow but
        # unbounded memory leak in long-running multi-tenant deployments. A
        # 300 s TTL (> the 120 s window) lets idle users' locks be reclaimed
        # while a still-active user always re-acquires a live lock.
        self._locks: TTLCache = TTLCache(maxsize=cache_maxsize, ttl=300)
        self._meta_lock = asyncio.Lock()          # guards _locks dict only


    async def _get_lock(self, uid: str) -> asyncio.Lock:
        async with self._meta_lock:
            if uid not in self._locks:
                self._locks[uid] = asyncio.Lock()
            return self._locks[uid]

    async def is_allowed(self, uid: str) -> bool:
        # HIGH-04: acquire a strong local reference to the lock inside the
        # meta_lock scope. The old code called _get_lock (which returned the
        # lock) and then awaited `async with lock:` separately — in between, the
        # 300 s-TTL _locks cache entry could be evicted, so a concurrent request
        # for the same uid would create a DIFFERENT lock and both coroutines
        # would hold non-overlapping locks, breaking serialization of the
        # sliding-window writes. Holding the reference here keeps the entry
        # live and re-inserting it refreshes the TTL so it can't be evicted
        # while a request is using it.
        async with self._meta_lock:
            lock = self._locks.get(uid)
            if lock is None:
                lock = asyncio.Lock()
            # Re-insert to refresh the TTL and guarantee the entry stays live.
            self._locks[uid] = lock
        now  = time.monotonic()
        cutoff = now - 60.0
        async with lock:

            ts = [t for t in self._cache.get(uid, []) if t > cutoff]
            if len(ts) >= self._max:
                self._cache[uid] = ts
                return False
            ts.append(now)
            self._cache[uid] = ts
            return True


def build_rate_limiter() -> _RedisRateLimiter | _InProcessRateLimiter:
    """
    Use Redis when REDIS_URL is configured; fall back to in-process otherwise.
    Logs which backend is active at startup so it's unambiguous in prod.
    """
    if REDIS_URL:
        logger.info("rate_limiter.backend", backend="redis", url=REDIS_URL)
        return _RedisRateLimiter(REDIS_URL, USER_RATE_LIMIT_PER_MINUTE)
    logger.warning(
        "rate_limiter.backend",
        backend="in_process",
        note="not safe for multi-replica deployments; set REDIS_URL",
    )
    return _InProcessRateLimiter(USER_RATE_LIMIT_PER_MINUTE)
