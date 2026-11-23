"""FastAPI app. Phase 0: health and readiness only; /v1 routes arrive in later phases."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from ledgerlens import __version__
from ledgerlens.cache import get_cache
from ledgerlens.config import get_settings
from ledgerlens.db import get_engine
from ledgerlens.storage import blob_service

settings = get_settings()
app = FastAPI(title="LedgerLens", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Doesn't touch dependencies."""
    return {"status": "ok", "version": __version__}


async def _check_postgres() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_cache() -> None:
    await get_cache().ping()


async def _check_blob() -> None:
    async with blob_service(settings) as blobs:
        await blobs.get_service_properties()


CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "postgres": _check_postgres,
    "cache": _check_cache,
    "blob": _check_blob,
}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Readiness: every backing service answers within 3 s."""

    async def run(fn: Callable[[], Awaitable[None]]) -> str:
        try:
            await asyncio.wait_for(fn(), timeout=3)
            return "ok"
        except Exception as exc:  # report, don't crash, so the operator sees which one failed
            return f"error: {type(exc).__name__}"

    names = list(CHECKS)
    results = await asyncio.gather(*(run(CHECKS[n]) for n in names))
    checks = dict(zip(names, results, strict=True))
    ready = all(v == "ok" for v in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ready, "checks": checks}
