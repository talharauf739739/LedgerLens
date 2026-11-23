"""ORM models. Change them only together with an Alembic migration (`alembic revision`)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(Base):
    """One uploaded document and its extraction lifecycle."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda e: [m.value for m in e]),
        default=JobStatus.QUEUED,
        index=True,
    )
    doc_type: Mapped[str | None] = mapped_column(String(64), index=True)
    blob_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None]
    # The full extraction result (fields, transactions, validation, markdown).
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # The FK is ON DELETE CASCADE in the database; let Postgres do it rather than having the
    # ORM try to null out job_id (which is NOT NULL) on audit rows it hasn't loaded.
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class AuditEvent(Base):
    """Append-only audit trail: model, prompt version, rule results, reviewer decisions."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(64))  # e.g. "extracted", "rules_run", "reviewed"
    actor: Mapped[str] = mapped_column(String(128))  # "system", agent name or reviewer id
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped[Job] = relationship(back_populates="audit_events")
