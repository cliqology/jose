"""Add job-source active/removed tracking, job reposts, and material version flag.

Revision ID: 0006_job_change_removal_detection
Revises: 0005_job_merge_candidates
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_job_removal"
down_revision = "0005_job_merge_candidates"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "job_sources",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "job_sources", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column("jobs", sa.Column("reposted_from_job_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_jobs_reposted_from_job_id",
        "jobs",
        "jobs",
        ["reposted_from_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_jobs_reposted_from_job_id", "jobs", ["reposted_from_job_id"])

    op.add_column(
        "job_versions",
        sa.Column("is_material", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("job_versions", "is_material")

    op.drop_index("ix_jobs_reposted_from_job_id", table_name="jobs")
    op.drop_constraint("fk_jobs_reposted_from_job_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "reposted_from_job_id")

    op.drop_column("job_sources", "removed_at")
    op.drop_column("job_sources", "is_active")
