"""Add consecutive_failures counter to sources.

Revision ID: 0008_source_health_dashboard
Revises: 0007_harden_task_queue
Create Date: 2026-07-30
"""

from alembic import op  # noqa: I001
import sqlalchemy as sa

revision = "0008_source_health_dashboard"
down_revision = "0007_harden_task_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("sources", "consecutive_failures")
