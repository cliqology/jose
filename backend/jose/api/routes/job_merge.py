import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from jose.api.deps import CurrentUser, DBSession
from jose.models import Company, Job, JobMergeCandidate
from jose.schemas import (
    JobMergeCandidateListRead,
    JobMergeCandidateRead,
    JobMergeResolveRequest,
)
from jose.services import job_merge as job_merge_service

router = APIRouter(prefix="/api/v1/job-merge-candidates", tags=["job-merge-candidates"])


def _job_summary(db: DBSession, user: CurrentUser, job_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.id == job_id, Job.user_id == user.id)
    ).first()
    assert row is not None
    job, company_name = row
    return {
        "id": job.id,
        "title": job.title,
        "company_name": company_name,
        "location": job.location,
        "application_url": job.application_url,
        "status": job.status,
    }


@router.get("", response_model=list[JobMergeCandidateListRead])
def list_job_merge_candidates(
    db: DBSession, user: CurrentUser, status: str = Query(default="pending")
) -> list[dict[str, Any]]:
    candidates = job_merge_service.list_merge_candidates(db, user, status)
    return [
        {
            "id": candidate.id,
            "status": candidate.status,
            "similarity_score": candidate.similarity_score,
            "matched_signals": candidate.matched_signals,
            "created_at": candidate.created_at,
            "job": _job_summary(db, user, candidate.job_id),
            "candidate_job": _job_summary(db, user, candidate.candidate_job_id),
        }
        for candidate in candidates
    ]


@router.post("/{candidate_id}/resolve", response_model=JobMergeCandidateRead)
def resolve_job_merge_candidate(
    candidate_id: uuid.UUID, payload: JobMergeResolveRequest, db: DBSession, user: CurrentUser
) -> JobMergeCandidate:
    try:
        if payload.action == "dismiss":
            return job_merge_service.dismiss_merge_candidate(db, user, candidate_id)
        if payload.keep is None:
            raise HTTPException(status_code=400, detail="keep is required for merge action")
        return job_merge_service.merge_candidate(db, user, candidate_id, payload.keep)
    except job_merge_service.MergeCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Merge candidate not found") from exc
    except job_merge_service.MergeCandidateNotPendingError as exc:
        raise HTTPException(status_code=409, detail="Merge candidate already resolved") from exc


@router.post("/{candidate_id}/unmerge", response_model=JobMergeCandidateRead)
def unmerge_job_merge_candidate(
    candidate_id: uuid.UUID, db: DBSession, user: CurrentUser
) -> JobMergeCandidate:
    try:
        return job_merge_service.unmerge_candidate(db, user, candidate_id)
    except job_merge_service.MergeCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Merge candidate not found") from exc
    except job_merge_service.MergeCandidateNotMergedError as exc:
        raise HTTPException(status_code=409, detail="Merge candidate is not merged") from exc
