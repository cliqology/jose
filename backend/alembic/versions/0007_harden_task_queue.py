"""Add task payload versioning and user timezone.

Revision ID: 0007_harden_task_queue
Revises: 0006_job_removal_detection
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_harden_task_queue"
down_revision = "0006_job_removal_detection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("payload_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(length=50),
            nullable=False,
            server_default="America/Los_Angeles",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
    op.drop_column("tasks", "payload_version")
