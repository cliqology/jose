"""Add user_decision to jobs.

Revision ID: 0009_job_decisions
Revises: 0008_source_health_dashboard
Create Date: 2026-07-30
"""

from alembic import op  # noqa: I001
import sqlalchemy as sa

revision = "0009_job_decisions"
down_revision = "0008_source_health_dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("user_decision", sa.String(length=20), nullable=True))
    op.create_index(
        "ix_jobs_user_decision", "jobs", ["user_id", "user_decision"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_user_decision", table_name="jobs")
    op.drop_column("jobs", "user_decision")
