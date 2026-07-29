import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from jose.models import Job, JobMergeCandidate, JobSource, JobVersion, SystemEvent, User


def utcnow() -> datetime:
    return datetime.now(UTC)


class MergeCandidateNotFoundError(Exception):
    pass


class MergeCandidateNotPendingError(Exception):
    pass


class MergeCandidateNotMergedError(Exception):
    pass


def list_merge_candidates(
    session: Session, user: User, status: str = "pending"
) -> list[JobMergeCandidate]:
    return list(
        session.scalars(
            select(JobMergeCandidate)
            .where(JobMergeCandidate.user_id == user.id, JobMergeCandidate.status == status)
            .order_by(JobMergeCandidate.created_at)
        ).all()
    )


def _get_candidate(session: Session, user: User, candidate_id: uuid.UUID) -> JobMergeCandidate:
    candidate = session.scalar(
        select(JobMergeCandidate).where(
            JobMergeCandidate.id == candidate_id, JobMergeCandidate.user_id == user.id
        )
    )
    if not candidate:
        raise MergeCandidateNotFoundError(str(candidate_id))
    return candidate


def dismiss_merge_candidate(
    session: Session, user: User, candidate_id: uuid.UUID
) -> JobMergeCandidate:
    candidate = _get_candidate(session, user, candidate_id)
    if candidate.status != "pending":
        raise MergeCandidateNotPendingError(str(candidate_id))
    candidate.status = "dismissed"
    candidate.resolved_at = utcnow()
    session.commit()
    session.refresh(candidate)
    return candidate


def merge_candidate(
    session: Session, user: User, candidate_id: uuid.UUID, keep: Literal["job", "candidate"]
) -> JobMergeCandidate:
    candidate = _get_candidate(session, user, candidate_id)
    if candidate.status != "pending":
        raise MergeCandidateNotPendingError(str(candidate_id))

    kept_job_id = candidate.job_id if keep == "job" else candidate.candidate_job_id
    merged_job_id = candidate.candidate_job_id if keep == "job" else candidate.job_id
    merged_job = session.get(Job, merged_job_id)
    assert merged_job is not None

    moved_source_ids: list[str] = []
    for link in session.scalars(
        select(JobSource).where(JobSource.job_id == merged_job_id, JobSource.user_id == user.id)
    ).all():
        existing_link = session.scalar(
            select(JobSource).where(
                JobSource.job_id == kept_job_id,
                JobSource.source_id == link.source_id,
                JobSource.user_id == user.id,
            )
        )
        if existing_link is None:
            link.job_id = kept_job_id
            moved_source_ids.append(str(link.id))
        elif link.last_seen_at > existing_link.last_seen_at:
            session.delete(existing_link)
            session.flush()
            link.job_id = kept_job_id
            moved_source_ids.append(str(link.id))
        else:
            session.delete(link)

    moved_version_ids: list[str] = []
    for version in session.scalars(
        select(JobVersion).where(JobVersion.job_id == merged_job_id)
    ).all():
        existing_version = session.scalar(
            select(JobVersion).where(
                JobVersion.job_id == kept_job_id, JobVersion.content_hash == version.content_hash
            )
        )
        if existing_version is None:
            version.job_id = kept_job_id
            moved_version_ids.append(str(version.id))
        else:
            session.delete(version)

    merged_job.status = "merged"
    merged_job.merged_into_job_id = kept_job_id

    candidate.status = "merged"
    candidate.resolved_at = utcnow()
    candidate.kept_job_id = kept_job_id
    candidate.merged_job_id = merged_job_id
    candidate.moved_job_source_ids = moved_source_ids
    candidate.moved_job_version_ids = moved_version_ids

    session.add(
        SystemEvent(
            user_id=user.id,
            event_type="job_merged",
            entity_type="job",
            entity_id=kept_job_id,
            message=f"Merged job {merged_job_id} into {kept_job_id}",
            data={
                "candidate_id": str(candidate.id),
                "kept_job_id": str(kept_job_id),
                "merged_job_id": str(merged_job_id),
            },
        )
    )
    session.commit()
    session.refresh(candidate)
    return candidate


def unmerge_candidate(session: Session, user: User, candidate_id: uuid.UUID) -> JobMergeCandidate:
    candidate = _get_candidate(session, user, candidate_id)
    if candidate.status != "merged":
        raise MergeCandidateNotMergedError(str(candidate_id))

    merged_job = session.get(Job, candidate.merged_job_id)
    assert merged_job is not None
    kept_job_id = candidate.kept_job_id

    source_ids = [uuid.UUID(value) for value in candidate.moved_job_source_ids]
    if source_ids:
        session.execute(
            update(JobSource).where(JobSource.id.in_(source_ids)).values(job_id=merged_job.id)
        )
    version_ids = [uuid.UUID(value) for value in candidate.moved_job_version_ids]
    if version_ids:
        session.execute(
            update(JobVersion).where(JobVersion.id.in_(version_ids)).values(job_id=merged_job.id)
        )

    merged_job.status = "active"
    merged_job.merged_into_job_id = None

    candidate.status = "dismissed"
    candidate.resolved_at = utcnow()

    session.add(
        SystemEvent(
            user_id=user.id,
            event_type="job_unmerged",
            entity_type="job",
            entity_id=kept_job_id,
            message=f"Unmerged job {merged_job.id} from {kept_job_id}",
            data={"candidate_id": str(candidate.id)},
        )
    )
    session.commit()
    session.refresh(candidate)
    return candidate
