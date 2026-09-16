"""
routes/greeting.py — Instant, personalised, time-aware greeting endpoint.

Architecture (production standard — matches Claude, Linear, Notion):
    - NO LLM calls. NO image-generation calls.
    - Greeting text + subline selected from curated YAML templates in
      greeting_config.yaml, seeded deterministically by date so text
      rotates daily but is consistent within the same day across all
      workers and replicas.
    - Background image selected from curated Unsplash URLs (same seed).
    - Redis-backed cache with TTLCache in-process fallback.
    - Response time: <5 ms (vs. 10–25 s with LLM + FLUX).

POST /greeting
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import structlog
import yaml
import redis.asyncio as aioredis
from cachetools import TTLCache
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from config import GREETING_CACHE_TTL, REDIS_URL
from auth_middleware import AuthenticatedUser, get_current_user, safe_user_id

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["greeting"])

# ── Nigeria timezone (WAT = UTC+1) ────────────────────────────────────────────
_NG_TZ = timezone(timedelta(hours=1))

# ── Project root ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent


# ══════════════════════════════════════════════════════════════════════════════
# Config loader — fail-fast at import time
# ══════════════════════════════════════════════════════════════════════════════

def _load_yaml(path: Path, label: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise RuntimeError(f"[greeting] FATAL: {label} not found at {path}")
    except yaml.YAMLError as e:
        raise RuntimeError(f"[greeting] FATAL: {label} is malformed YAML: {e}")


_cfg_path = (
    _ROOT / "greeting_config.yaml"
    if (_ROOT / "greeting_config.yaml").exists()
    else _ROOT / "greetings.yaml"
)
_GREETING_CFG = _load_yaml(_cfg_path, _cfg_path.name)

_REQUIRED_KEYS = ("fallback_greetings", "fallback_sublines", "fallback_images")
_missing = [k for k in _REQUIRED_KEYS if k not in _GREETING_CFG]
if _missing:
    raise RuntimeError(
        f"[greeting] FATAL: {_cfg_path.name} is missing required keys: {_missing}"
    )

# Unpack curated content
_GREETINGS: dict  = _GREETING_CFG["fallback_greetings"]   # period → string template
_SUBLINES:  dict  = _GREETING_CFG["fallback_sublines"]    # period → string template
_IMAGES:    dict  = _GREETING_CFG["fallback_images"]      # period → list[str]

# Optional: richer multi-variant sublines  (greeting_config.yaml can add
# a "subline_variants" block; falls back to "fallback_sublines" if absent)
_SUBLINE_VARIANTS: dict = _GREETING_CFG.get("subline_variants", {})

logger.info(
    "greeting.config_loaded",
    source=_cfg_path.name,
    periods=list(_GREETINGS.keys()),
)


# ══════════════════════════════════════════════════════════════════════════════
# Deterministic helpers — same output across all workers for the same day
# ══════════════════════════════════════════════════════════════════════════════

def _stable_hash(*parts: str) -> int:
    """SHA-256 based hash — stable across processes (unlike built-in hash())."""
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()
    return int(digest, 16)


def _pick(items: list, *seed_parts: str) -> str:
    """Pick a list item deterministically using a date-seeded hash."""
    if not items:
        return ""
    idx = _stable_hash(*seed_parts) % len(items)
    return items[idx]


def _resolve_subline(period: str, first_name: str, today: str) -> str:
    """
    Pick a subline. If greeting_config.yaml has a ``subline_variants`` block
    with multiple options per period, rotate through them daily.
    Fall back to the single ``fallback_sublines`` string.
    """
    variants = _SUBLINE_VARIANTS.get(period)
    if variants and isinstance(variants, list) and len(variants) > 1:
        return _pick(variants, today, period, first_name)

    tmpl = _SUBLINES.get(period, _SUBLINES.get("default", "How can I help?"))
    return tmpl.format(first_name=first_name)


def _build_greeting(first_name: str, period: str, today: str) -> dict:
    """Build the final greeting dict from curated YAML data — no network calls."""
    greeting_tmpl = _GREETINGS.get(period, _GREETINGS.get("default", "Hello, {first_name}."))
    greeting      = greeting_tmpl.format(first_name=first_name)

    subline       = _resolve_subline(period, first_name, today)

    image_list    = _IMAGES.get(period, _IMAGES.get("morning", []))
    image_url     = _pick(image_list, today, period) if image_list else ""

    return {
        "greeting":  greeting,
        "subline":   subline,
        "image_url": image_url,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Redis-backed cache with TTLCache in-process fallback
# ══════════════════════════════════════════════════════════════════════════════

_CACHE_VERSION = "v3"   # bump when response schema changes

_redis: aioredis.Redis | None = None
_redis_available: bool = True
_redis_lock = asyncio.Lock()
_redis_last_failure: float = 0.0
_REDIS_RETRY_COOLDOWN_S = 30.0

_greeting_cache: TTLCache = TTLCache(maxsize=500, ttl=GREETING_CACHE_TTL)
_cache_lock = asyncio.Lock()


async def _get_redis() -> aioredis.Redis | None:
    global _redis, _redis_available, _redis_last_failure

    if _redis_available and _redis is not None:
        return _redis
    if not _redis_available and (time.time() - _redis_last_failure) < _REDIS_RETRY_COOLDOWN_S:
        return None

    async with _redis_lock:
        if _redis_available and _redis is not None:
            return _redis
        if not _redis_available and (time.time() - _redis_last_failure) < _REDIS_RETRY_COOLDOWN_S:
            return None
        try:
            candidate = aioredis.from_url(
                REDIS_URL, decode_responses=True, socket_connect_timeout=2
            )
            await candidate.ping()
            _redis = candidate
            _redis_available = True
            logger.info("greeting.redis_connected")
        except Exception as e:
            logger.warning(
                "greeting.redis_unavailable",
                error=str(e),
                retry_in_s=_REDIS_RETRY_COOLDOWN_S,
                note="falling back to in-process TTLCache",
            )
            _redis_available = False
            _redis_last_failure = time.time()
            _redis = None
    return _redis


async def _get_cached(key: str) -> dict | None:
    r = await _get_redis()
    if r:
        try:
            raw = await r.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning("greeting.redis_get_error", error=str(e))
    async with _cache_lock:
        return _greeting_cache.get(key)


async def _set_cached(key: str, value: dict) -> None:
    r = await _get_redis()
    if r:
        try:
            await r.setex(key, GREETING_CACHE_TTL, json.dumps(value))
            return
        except Exception as e:
            logger.warning("greeting.redis_set_error", error=str(e))
    async with _cache_lock:
        _greeting_cache[key] = value


# ══════════════════════════════════════════════════════════════════════════════
# Request model & route
# ══════════════════════════════════════════════════════════════════════════════

class GreetingRequest(BaseModel):
    thread_id: str = "default"


@router.post("/greeting")
async def generate_greeting(
    http_request: Request,
    body: GreetingRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Return an instant personalised greeting.

    Response time target: <10 ms (cache hit <1 ms).
    No LLM calls. No image generation. No external dependencies.
    """
    req_id     = str(uuid.uuid4())[:8]
    req_logger = logger.bind(req_id=req_id, user=user.email)
    t0         = time.perf_counter()

    # ── Derive display name ──────────────────────────────────────────────────
    raw_first  = (user.name.split()[0] if user.name else "there")
    first_name = re.sub(r"[^\w\s]", "", raw_first).strip()[:32] or "there"

    # ── Current time in Nigeria (WAT = UTC+1) ────────────────────────────────
    now      = datetime.now(_NG_TZ)
    hour     = now.hour
    today    = now.strftime("%Y-%m-%d")

    period = (
        "dawn"      if  5 <= hour <  9 else
        "morning"   if  9 <= hour < 12 else
        "afternoon" if 12 <= hour < 17 else
        "evening"   if 17 <= hour < 21 else
        "night"
    )

    # ── Cache key: user + 5-minute bucket (greeting stable for 5 min) ────────
    user_hash  = hashlib.sha256(user.email.encode()).hexdigest()[:16]
    time_bucket = f"{today}-{hour}-{(now.minute // 5) * 5}"
    cache_key   = f"greeting:{_CACHE_VERSION}:{user_hash}:{time_bucket}"

    cached = await _get_cached(cache_key)
    if cached:
        req_logger.debug("greeting.cache_hit", period=period)
        return cached

    # ── Build greeting from curated YAML (pure deterministic logic) ──────────
    result = _build_greeting(first_name, period, today)

    await _set_cached(cache_key, result)

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    req_logger.info(
        "greeting.ok",
        period=period,
        elapsed_ms=elapsed_ms,
        cache_key=cache_key,
    )
    return result