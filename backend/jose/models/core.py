import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jose.db.base import Base
from jose.models.base import TimestampMixin, UserOwnedMixin, UUIDPrimaryKeyMixin, utcnow


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Source(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("user_id", "url", name="uq_sources_user_url"),
        Index("ix_sources_user_enabled", "user_id", "enabled"),
    )

    name: Mapped[str] = mapped_column(String(250))
    url: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="user_added")
    portfolio_firm: Mapped[str | None] = mapped_column(String(250))
    adapter: Mapped[str] = mapped_column(String(50), default="auto")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    collection_frequency: Mapped[str] = mapped_column(String(50), default="daily")
    notes: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_job_count: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    detected_platform: Mapped[str | None] = mapped_column(String(100))
    detection_status: Mapped[str | None] = mapped_column(String(20))
    detected_application_url: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list["SourceRun"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SourceRun(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "source_runs"
    __table_args__ = (Index("ix_source_runs_source_started", "source_id", "started_at"),)

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_created: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    jobs_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(150))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    source: Mapped[Source] = relationship(back_populates="runs")


class SourceImportRun(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "source_import_runs"

    filename: Mapped[str] = mapped_column(String(500))
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, default=0)
    flagged_rows: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Company(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("user_id", "normalized_name", name="uq_company_name"),)

    name: Mapped[str] = mapped_column(String(250))
    normalized_name: Mapped[str] = mapped_column(String(250), index=True)
    website_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_jobs_user_fingerprint"),
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_user_first_seen", "user_id", "first_seen_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(350))
    normalized_title: Mapped[str] = mapped_column(String(350), index=True)
    description_text: Mapped[str | None] = mapped_column(Text)
    description_html: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(String(250))
    location: Mapped[str | None] = mapped_column(String(350))
    remote_type: Mapped[str | None] = mapped_column(String(50))
    employment_type: Mapped[str | None] = mapped_column(String(100))
    compensation_min: Mapped[int | None] = mapped_column(Integer)
    compensation_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(10))
    application_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    ats_type: Mapped[str | None] = mapped_column(String(50))
    external_job_id: Mapped[str | None] = mapped_column(String(250))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="active")
    fingerprint: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    company: Mapped[Company] = relationship()


class JobSource(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "job_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", "source_id", name="uq_job_source_link"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    source_job_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobVersion(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "content_hash", name="uq_job_version_hash"),
        Index("ix_job_versions_job_seen", "job_id", "seen_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Task(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_claim", "status", "scheduled_at", "priority"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_tasks_idempotency"),
    )

    task_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(250))
    last_error: Mapped[str | None] = mapped_column(Text)


class SystemEvent(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "system_events"

    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
