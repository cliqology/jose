"""Phase 0/1 core schema.

Revision ID: 0001_phase_0_1
Revises:
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_phase_0_1"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "sources",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("portfolio_firm", sa.String(length=250), nullable=True),
        sa.Column("adapter", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("collection_frequency", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "url", name="uq_sources_user_url"),
    )
    op.create_index("ix_sources_user_id", "sources", ["user_id"], unique=False)
    op.create_index("ix_sources_user_enabled", "sources", ["user_id", "enabled"], unique=False)

    op.create_table(
        "source_runs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jobs_found", sa.Integer(), nullable=False),
        sa.Column("jobs_created", sa.Integer(), nullable=False),
        sa.Column("jobs_updated", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=150), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_runs_source_id", "source_runs", ["source_id"], unique=False)
    op.create_index("ix_source_runs_status", "source_runs", ["status"], unique=False)
    op.create_index("ix_source_runs_user_id", "source_runs", ["user_id"], unique=False)
    op.create_index("ix_source_runs_source_started", "source_runs", ["source_id", "started_at"], unique=False)

    op.create_table(
        "companies",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("normalized_name", sa.String(length=250), nullable=False),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_company_name"),
    )
    op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"], unique=False)
    op.create_index("ix_companies_user_id", "companies", ["user_id"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("company_id", UUID, nullable=False),
        sa.Column("title", sa.String(length=350), nullable=False),
        sa.Column("normalized_title", sa.String(length=350), nullable=False),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("department", sa.String(length=250), nullable=True),
        sa.Column("location", sa.String(length=350), nullable=True),
        sa.Column("remote_type", sa.String(length=50), nullable=True),
        sa.Column("employment_type", sa.String(length=100), nullable=True),
        sa.Column("compensation_min", sa.Integer(), nullable=True),
        sa.Column("compensation_max", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("application_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("ats_type", sa.String(length=50), nullable=True),
        sa.Column("external_job_id", sa.String(length=250), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", JSONB, nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_jobs_user_fingerprint"),
    )
    op.create_index("ix_jobs_company_id", "jobs", ["company_id"], unique=False)
    op.create_index("ix_jobs_normalized_title", "jobs", ["normalized_title"], unique=False)
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"], unique=False)
    op.create_index("ix_jobs_user_status", "jobs", ["user_id", "status"], unique=False)
    op.create_index("ix_jobs_user_first_seen", "jobs", ["user_id", "first_seen_at"], unique=False)

    op.create_table(
        "job_sources",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("source_job_url", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "job_id", "source_id", name="uq_job_source_link"),
    )
    op.create_index("ix_job_sources_job_id", "job_sources", ["job_id"], unique=False)
    op.create_index("ix_job_sources_source_id", "job_sources", ["source_id"], unique=False)
    op.create_index("ix_job_sources_user_id", "job_sources", ["user_id"], unique=False)

    op.create_table(
        "job_versions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "content_hash", name="uq_job_version_hash"),
    )
    op.create_index("ix_job_versions_job_id", "job_versions", ["job_id"], unique=False)
    op.create_index("ix_job_versions_user_id", "job_versions", ["user_id"], unique=False)
    op.create_index("ix_job_versions_job_seen", "job_versions", ["job_id", "seen_at"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=200), nullable=True),
        sa.Column("idempotency_key", sa.String(length=250), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_tasks_idempotency"),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)
    op.create_index("ix_tasks_task_type", "tasks", ["task_type"], unique=False)
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"], unique=False)
    op.create_index("ix_tasks_claim", "tasks", ["status", "scheduled_at", "priority"], unique=False)

    op.create_table(
        "system_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", UUID, nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONB, nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_events_event_type", "system_events", ["event_type"], unique=False)
    op.create_index("ix_system_events_user_id", "system_events", ["user_id"], unique=False)


def downgrade() -> None:
    for table in [
        "system_events",
        "tasks",
        "job_versions",
        "job_sources",
        "jobs",
        "companies",
        "source_runs",
        "sources",
        "users",
    ]:
        op.drop_table(table)
