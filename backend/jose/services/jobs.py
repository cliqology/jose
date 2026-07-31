import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jose.models import Company, Job, JobSource, JobVersion, Source, SystemEvent, User

HIDDEN_BY_DEFAULT_DECISIONS = ("irrelevant", "archived")


class JobNotFoundError(Exception):
    pass


class InvalidDateFilterError(Exception):
    pass


def _parse_date_bound(value: str | None, *, end_of_day: bool) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidDateFilterError(f"Invalid date filter value: {value!r}") from exc
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


def get_job_detail(session: Session, user: User, job_id: uuid.UUID) -> dict[str, Any]:
    row = session.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.id == job_id, Job.user_id == user.id)
    ).first()
    if row is None:
        raise JobNotFoundError(str(job_id))
    job, company_name = row

    source_rows = session.execute(
        select(JobSource, Source.name, Source.category)
        .join(Source, Source.id == JobSource.source_id)
        .where(JobSource.job_id == job.id, JobSource.user_id == user.id)
        .order_by(JobSource.first_seen_at)
    ).all()
    sources = [
        {
            "source_id": link.source_id,
            "source_name": source_name,
            "source_category": source_category,
            "source_job_url": link.source_job_url,
            "is_active": link.is_active,
            "first_seen_at": link.first_seen_at,
            "last_seen_at": link.last_seen_at,
        }
        for link, source_name, source_category in source_rows
    ]

    versions = [
        {
            "seen_at": version.seen_at,
            "is_material": version.is_material,
            "content_hash": version.content_hash,
        }
        for version in session.scalars(
            select(JobVersion)
            .where(JobVersion.job_id == job.id)
            .order_by(JobVersion.seen_at.desc())
        ).all()
    ]

    return {
        "id": job.id,
        "company_name": company_name,
        "title": job.title,
        "normalized_title": job.normalized_title,
        "description_text": job.description_text,
        "description_html": job.description_html,
        "department": job.department,
        "location": job.location,
        "remote_type": job.remote_type,
        "employment_type": job.employment_type,
        "compensation_min": job.compensation_min,
        "compensation_max": job.compensation_max,
        "currency": job.currency,
        "application_url": job.application_url,
        "canonical_url": job.canonical_url,
        "ats_type": job.ats_type,
        "published_at": job.published_at,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "status": job.status,
        "reposted_from_job_id": job.reposted_from_job_id,
        "user_decision": job.user_decision,
        "sources": sources,
        "versions": versions,
    }


def set_job_decision(
    session: Session, user: User, job_id: uuid.UUID, decision: str | None
) -> Job:
    job = session.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if job is None:
        raise JobNotFoundError(str(job_id))

    previous = job.user_decision
    job.user_decision = decision
    session.add(
        SystemEvent(
            user_id=user.id,
            event_type="job_decision_set",
            entity_type="job",
            entity_id=job.id,
            message=f"Job decision set to {decision!r} (was {previous!r})",
            data={"previous": previous, "decision": decision},
        )
    )
    session.commit()
    session.refresh(job)
    return job
