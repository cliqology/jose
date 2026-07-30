from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from jose.api.deps import CurrentUser, DBSession
from jose.models import Company, Job

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.user_id == user.id, Job.status != "merged")
        .order_by(Job.first_seen_at.desc())
        .limit(limit)
    ).all()
    return [
        {
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
        }
        for job, company_name in rows
    ]
