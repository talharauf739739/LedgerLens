"""Live-service tests. Run: docker compose up -d, alembic upgrade head, pytest -m integration."""

import uuid

import pytest
from sqlalchemy import select

from ledgerlens.cache import get_cache
from ledgerlens.db import AuditEvent, Job, JobStatus, get_engine, get_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def fresh_connections() -> None:
    # Engines/clients bind to an event loop; each test gets its own loop.
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    get_cache.cache_clear()


async def test_job_with_audit_roundtrip() -> None:
    job_id = uuid.uuid4()
    async with get_sessionmaker()() as session:
        session.add(Job(id=job_id, blob_path="raw/x.pdf", sha256="0" * 64))
        session.add(AuditEvent(job_id=job_id, event="queued", actor="system", detail={"v": 1}))
        await session.commit()

    async with get_sessionmaker()() as session:
        job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
        assert job.status is JobStatus.QUEUED
        await session.delete(job)
        await session.commit()
    await get_engine().dispose()


async def test_cache_roundtrip() -> None:
    cache = get_cache()
    await cache.set("ll:test:v0:x", "1", ex=10)
    assert await cache.get("ll:test:v0:x") == "1"
    await cache.aclose()
