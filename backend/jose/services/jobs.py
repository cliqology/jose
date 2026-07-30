import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jose.models import Company, Job, JobSource, User

HIDDEN_BY_DEFAULT_DECISIONS = ("irrelevant", "archived")


class JobNotFoundError(Exception):
    pass


def _parse_date_bound(value: str | None, *, end_of_day: bool) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if end_of_day:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def _job_row_to_dict(job: Job, company_name: str) -> dict[str, Any]:
    return {
        "id": job.id,
        "company_name": company_name,
        "title": job.title,
        "location": job.location,
        "application_url": job.application_url,
        "ats_type": job.ats_type,
        "published_at": job.published_at,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "status": job.status,
        "reposted_from_job_id": job.reposted_from_job_id,
        "user_decision": job.user_decision,
    }


def list_jobs(
    session: Session,
    user: User,
    *,
    company: str | None = None,
    title: str | None = None,
    source_id: uuid.UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    ats_type: str | None = None,
    status: str | None = None,
    decision: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = (
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.user_id == user.id, Job.status != "merged")
    )

    if company:
        query = query.where(Company.name.ilike(f"%{company}%"))
    if title:
        query = query.where(Job.title.ilike(f"%{title}%"))
    if location:
        query = query.where(Job.location.ilike(f"%{location}%"))
    if ats_type:
        query = query.where(Job.ats_type == ats_type)
    if status:
        query = query.where(Job.status == status)

    from_bound = _parse_date_bound(date_from, end_of_day=False)
    if from_bound:
        query = query.where(Job.first_seen_at >= from_bound)
    to_bound = _parse_date_bound(date_to, end_of_day=True)
    if to_bound:
        query = query.where(Job.first_seen_at <= to_bound)

    if source_id:
        query = query.where(
            Job.id.in_(
                select(JobSource.job_id).where(
                    JobSource.source_id == source_id, JobSource.user_id == user.id
                )
            )
        )

    if decision:
        query = query.where(Job.user_decision.in_(decision))
    else:
        query = query.where(
            or_(
                Job.user_decision.is_(None),
                Job.user_decision.notin_(HIDDEN_BY_DEFAULT_DECISIONS),
            )
        )

    rows = session.execute(
        query.order_by(Job.first_seen_at.desc()).limit(limit).offset(offset)
    ).all()
    return [_job_row_to_dict(job, company_name) for job, company_name in rows]
