"""Add jobs_rejected to source_runs.

Revision ID: 0003_source_run_jobs_rejected
Revises: 0002_source_import_runs
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_source_run_jobs_rejected"
down_revision = "0002_source_import_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_runs",
        sa.Column("jobs_rejected", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("source_runs", "jobs_rejected", server_default=None)


def downgrade() -> None:
    op.drop_column("source_runs", "jobs_rejected")
