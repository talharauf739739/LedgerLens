"""Live-service tests. Run: docker compose up -d, alembic upgrade head, pytest -m integration."""

import json
import os
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from ledgerlens.cache import get_cache
from ledgerlens.config import Settings
from ledgerlens.db import AuditEvent, Job, JobStatus, get_engine, get_sessionmaker
from ledgerlens.storage import blob_service, ensure_resources, jobs_queue

# Public, well-known emulator credentials (Azurite/Floci devstoreaccount1). Not a secret.
FLOCI = (
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://localhost:4577/devstoreaccount1;"
    "QueueEndpoint=http://localhost:4577/devstoreaccount1-queue;"
)

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

    async with get_sessionmaker()() as session:
        left = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.job_id == job_id)
        )
        assert left == 0  # ON DELETE CASCADE removed the audit rows
    await get_engine().dispose()


async def test_cache_roundtrip() -> None:
    cache = get_cache()
    await cache.set("ll:test:v0:x", "1", ex=10)
    assert await cache.get("ll:test:v0:x") == "1"
    await cache.aclose()


@pytest.fixture
def storage_settings() -> Settings:
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", FLOCI)
    return Settings(
        azure_storage_connection_string=SecretStr(conn),
        blob_container=f"it-{uuid.uuid4().hex[:8]}",
        jobs_queue=f"it-{uuid.uuid4().hex[:8]}",
    )


async def test_blob_and_queue_roundtrip(storage_settings: Settings) -> None:
    s = storage_settings
    await ensure_resources(s)
    await ensure_resources(s)  # idempotent

    async with blob_service(s) as blobs:
        blob = blobs.get_blob_client(s.blob_container, "raw/sample.pdf")
        await blob.upload_blob(b"%PDF-1.7 synthetic", overwrite=True)
        assert await (await blob.download_blob()).readall() == b"%PDF-1.7 synthetic"
        await blobs.delete_container(s.blob_container)

    job = {"job_id": str(uuid.uuid4()), "blob_path": "raw/sample.pdf"}
    async with jobs_queue(s) as queue:
        await queue.send_message(json.dumps(job))
        received = [m async for m in queue.receive_messages(max_messages=5, visibility_timeout=5)]
        assert [json.loads(m.content) for m in received] == [job]
        await queue.delete_message(received[0])
        await queue.delete_queue()
