"""Valkey/Redis cache. A cache only: anything stored here must be recomputable.

Keys are namespaced and versioned so a prompt or OCR change never serves stale output:
``ll:{kind}:{version}:{sha256-of-input}``.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from redis.asyncio import Redis

from ledgerlens.config import get_settings

DEFAULT_TTL_SECONDS = 7 * 24 * 3600


@lru_cache
def get_cache() -> Redis:
    return Redis.from_url(get_settings().cache_url, decode_responses=True)


def cache_key(kind: str, version: str, payload: bytes | str) -> str:
    data = payload.encode() if isinstance(payload, str) else payload
    return f"ll:{kind}:{version}:{hashlib.sha256(data).hexdigest()}"
