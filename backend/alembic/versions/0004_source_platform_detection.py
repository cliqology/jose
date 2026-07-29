"""Add platform detection fields to sources.

Revision ID: 0004_source_platform_detection
Revises: 0003_source_run_jobs_rejected
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_source_platform_detection"
down_revision = "0003_source_run_jobs_rejected"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("detected_platform", sa.String(length=100), nullable=True))
    op.add_column("sources", sa.Column("detection_status", sa.String(length=20), nullable=True))
    op.add_column("sources", sa.Column("detected_application_url", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "detected_at")
    op.drop_column("sources", "detected_application_url")
    op.drop_column("sources", "detection_status")
    op.drop_column("sources", "detected_platform")
