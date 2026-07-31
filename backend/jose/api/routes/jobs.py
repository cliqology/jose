import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from jose.api.deps import CurrentUser, DBSession
from jose.schemas import JobDecisionRead, JobDecisionUpdate, JobDetailRead
from jose.services import jobs as jobs_service

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    company: str | None = None,
    title: str | None = None,
    source_id: uuid.UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    ats_type: str | None = None,
    status: str | None = None,
    decision: list[str] | None = Query(default=None),  # noqa: B008
) -> list[dict[str, Any]]:
    try:
        return jobs_service.list_jobs(
            db,
            user,
            company=company,
            title=title,
            source_id=source_id,
            date_from=date_from,
            date_to=date_to,
            location=location,
            ats_type=ats_type,
            status=status,
            decision=decision,
            limit=limit,
            offset=offset,
        )
    except jobs_service.InvalidDateFilterError as exc:
        raise HTTPException(status_code=422, detail="Invalid date filter") from exc


@router.get("/{job_id}", response_model=JobDetailRead)
def get_job(job_id: uuid.UUID, db: DBSession, user: CurrentUser) -> dict[str, Any]:
    try:
        return jobs_service.get_job_detail(db, user, job_id)
    except jobs_service.JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@router.patch("/{job_id}/decision", response_model=JobDecisionRead)
def update_job_decision(
    job_id: uuid.UUID, payload: JobDecisionUpdate, db: DBSession, user: CurrentUser
):
    decision = payload.decision.value if payload.decision is not None else None
    try:
        return jobs_service.set_job_decision(db, user, job_id, decision)
    except jobs_service.JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
