"""Add job merge candidates table and merged_into_job_id column.

Revision ID: 0005_job_merge_candidates
Revises: 0004_source_platform_detection
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_job_merge_candidates"
down_revision = "0004_source_platform_detection"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("jobs", sa.Column("merged_into_job_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_jobs_merged_into_job_id",
        "jobs",
        "jobs",
        ["merged_into_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_jobs_merged_into_job_id", "jobs", ["merged_into_job_id"])

    op.create_table(
        "job_merge_candidates",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("candidate_job_id", UUID, nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("matched_signals", JSONB, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kept_job_id", UUID, nullable=True),
        sa.Column("merged_job_id", UUID, nullable=True),
        sa.Column("moved_job_source_ids", JSONB, nullable=False),
        sa.Column("moved_job_version_ids", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kept_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merged_job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_merge_candidates_user_id", "job_merge_candidates", ["user_id"])
    op.create_index("ix_job_merge_candidates_job_id", "job_merge_candidates", ["job_id"])
    op.create_index(
        "ix_job_merge_candidates_candidate_job_id", "job_merge_candidates", ["candidate_job_id"]
    )
    op.create_index(
        "ix_job_merge_candidates_user_status", "job_merge_candidates", ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_merge_candidates_user_status", table_name="job_merge_candidates")
    op.drop_index("ix_job_merge_candidates_candidate_job_id", table_name="job_merge_candidates")
    op.drop_index("ix_job_merge_candidates_job_id", table_name="job_merge_candidates")
    op.drop_index("ix_job_merge_candidates_user_id", table_name="job_merge_candidates")
    op.drop_table("job_merge_candidates")
    op.drop_index("ix_jobs_merged_into_job_id", table_name="jobs")
    op.drop_constraint("fk_jobs_merged_into_job_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "merged_into_job_id")
