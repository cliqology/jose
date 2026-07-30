from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jose.models import Job, JobVersion, Source, Task, User
from jose.schemas import DashboardSummary


def get_dashboard_summary(session: Session, user: User) -> DashboardSummary:
    since = datetime.now(UTC) - timedelta(hours=24)

    jobs_new = (
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.status != "merged", Job.first_seen_at >= since)
        )
        or 0
    )

    return DashboardSummary(
        sources_total=session.scalar(
            select(func.count()).select_from(Source).where(Source.user_id == user.id)
        )
        or 0,
        sources_enabled=session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.user_id == user.id, Source.enabled.is_(True))
        )
        or 0,
        sources_failing=session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.user_id == user.id, Source.last_error.is_not(None))
        )
        or 0,
        jobs_total=session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.status != "merged")
        )
        or 0,
        jobs_seen_last_24h=jobs_new,
        jobs_new_last_24h=jobs_new,
        jobs_changed_last_24h=session.scalar(
            select(func.count(func.distinct(JobVersion.job_id)))
            .select_from(JobVersion)
            .join(Job, Job.id == JobVersion.job_id)
            .where(
                Job.user_id == user.id,
                Job.status != "merged",
                JobVersion.is_material.is_(True),
                JobVersion.seen_at >= since,
            )
        )
        or 0,
        jobs_removed_last_24h=session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.status == "removed", Job.removed_at >= since)
        )
        or 0,
        jobs_reposted_last_24h=session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.user_id == user.id,
                Job.status != "merged",
                Job.reposted_from_job_id.is_not(None),
                Job.first_seen_at >= since,
            )
        )
        or 0,
        queued_tasks=session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user.id, Task.status == "queued")
        )
        or 0,
        running_tasks=session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user.id, Task.status == "running")
        )
        or 0,
    )
