import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from jose.collectors import get_collector
from jose.collectors.base import CollectedJob
from jose.collectors.utils import (
    COMPANY_ALIAS_THRESHOLD,
    FUZZY_MATCH_THRESHOLD,
    TITLE_MATCH_THRESHOLD,
    canonicalize_url,
    fuzzy_match_score,
    job_fingerprint,
    material_hash,
    normalize_name,
    normalize_title,
    stable_hash,
)
from jose.config import get_settings
from jose.models import Company, Job, JobMergeCandidate, JobSource, JobVersion, Source, SourceRun


def utcnow() -> datetime:
    return datetime.now(UTC)


def collect_source(session: Session, source_id: uuid.UUID) -> SourceRun:
    source = session.get(Source, source_id)
    if not source:
        raise ValueError(f"Source not found: {source_id}")

    source.last_attempt_at = utcnow()
    run = SourceRun(user_id=source.user_id, source_id=source.id, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        collector = get_collector(source.url, source.adapter)
        collect_url = (
            source.detected_application_url
            if source.detection_status == "supported" and source.detected_application_url
            else source.url
        )
        result = collector.collect(source.name, collect_url)
        created = 0
        updated = 0
        for item in result.jobs:
            was_created, was_updated = _upsert_job(session, source, item)
            created += int(was_created)
            updated += int(was_updated)

        _sweep_inactive_job_sources(session, source, run.started_at)
        session.commit()

        run = session.get(SourceRun, run.id)
        source = session.get(Source, source.id)
        assert run is not None and source is not None
        run.status = "success"
        run.completed_at = utcnow()
        run.jobs_found = len(result.jobs)
        run.jobs_created = created
        run.jobs_updated = updated
        run.jobs_rejected = result.rejected_count
        source.last_success_at = utcnow()
        source.last_job_count = len(result.jobs)
        source.last_error = None
        session.commit()
        return run
    except Exception as exc:
        session.rollback()
        run = session.get(SourceRun, run.id)
        source = session.get(Source, source_id)
        if run and source:
            run.status = "failed"
            run.completed_at = utcnow()
            run.error_type = type(exc).__name__
            run.error_message = str(exc)[:4000]
            source.last_error = f"{type(exc).__name__}: {exc}"[:4000]
            session.commit()
        raise


def _sweep_inactive_job_sources(
    session: Session, source: Source, run_started_at: datetime
) -> None:
    stale_links = session.scalars(
        select(JobSource).where(
            JobSource.source_id == source.id,
            JobSource.is_active.is_(True),
            JobSource.last_seen_at < run_started_at,
        )
    ).all()
    affected_job_ids: set[uuid.UUID] = set()
    for link in stale_links:
        link.is_active = False
        link.removed_at = utcnow()
        affected_job_ids.add(link.job_id)

    # `SessionLocal` is configured with `autoflush=False`, so the `still_active`
    # query below would not otherwise see the `is_active = False` updates just
    # made above.
    session.flush()

    for job_id in affected_job_ids:
        still_active = session.scalar(
            select(JobSource).where(JobSource.job_id == job_id, JobSource.is_active.is_(True))
        )
        if still_active is None:
            job = session.get(Job, job_id)
            if job is not None and job.status == "active":
                job.status = "removed"
                job.removed_at = utcnow()


def _find_fuzzy_candidate(
    session: Session, user_id: uuid.UUID, company_name: str, title: str, location: str | None
) -> tuple[Job, dict[str, float]] | None:
    rows = session.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.user_id == user_id, Job.status == "active")
    ).all()
    best: tuple[Job, dict[str, float]] | None = None
    for candidate_job, candidate_company_name in rows:
        scores = fuzzy_match_score(
            company_name,
            title,
            location or "",
            candidate_company_name,
            candidate_job.title,
            candidate_job.location or "",
        )
        if scores["company"] < COMPANY_ALIAS_THRESHOLD:
            continue
        if scores["title"] < TITLE_MATCH_THRESHOLD:
            continue
        if scores["composite"] < FUZZY_MATCH_THRESHOLD:
            continue
        if best is None or scores["composite"] > best[1]["composite"]:
            best = (candidate_job, scores)
    return best


def _resolve_merge_target(session: Session, job: Job) -> Job | None:
    """Follow `merged_into_job_id` forward from a merged-away job to its survivor.

    A merged-away job keeps its fingerprint, so a later collection run from its
    original source still matches the tombstone on the Tier 0 fingerprint lookup.
    Returning the survivor keeps the tombstone tombstoned instead of resurrecting it.

    Returns `None` when the chain is broken (dangling or cyclical `merged_into_job_id`,
    or a survivor owned by a different user), so the caller can fall back to the
    normal Tier 1 / create path.
    """
    seen: set[uuid.UUID] = {job.id}
    current = job
    while current.status == "merged":
        target_id = current.merged_into_job_id
        if target_id is None or target_id in seen:
            return None
        survivor = session.get(Job, target_id)
        if survivor is None or survivor.user_id != job.user_id:
            return None
        seen.add(survivor.id)
        current = survivor
    return current


def _flag_fuzzy_duplicate(
    session: Session,
    user_id: uuid.UUID,
    new_job: Job,
    candidate_job: Job,
    scores: dict[str, float],
) -> JobMergeCandidate | None:
    existing = session.scalar(
        select(JobMergeCandidate).where(
            JobMergeCandidate.user_id == user_id,
            JobMergeCandidate.status != "pending",
            or_(
                and_(
                    JobMergeCandidate.job_id == new_job.id,
                    JobMergeCandidate.candidate_job_id == candidate_job.id,
                ),
                and_(
                    JobMergeCandidate.job_id == candidate_job.id,
                    JobMergeCandidate.candidate_job_id == new_job.id,
                ),
            ),
        )
    )
    if existing:
        return None
    merge_candidate = JobMergeCandidate(
        user_id=user_id,
        job_id=new_job.id,
        candidate_job_id=candidate_job.id,
        similarity_score=scores["composite"],
        matched_signals={
            "company": scores["company"],
            "title": scores["title"],
            "location": scores["location"],
        },
        status="pending",
    )
    session.add(merge_candidate)
    return merge_candidate


def _upsert_job(session: Session, source: Source, item: CollectedJob) -> tuple[bool, bool]:
    if not item.application_url:
        raise ValueError(f"Collected job has no application URL: {item.title}")

    raw_payload = item.raw_payload if get_settings().collector_retain_raw_payload else {}
    company_name = item.company_name.strip() or source.name
    normalized_company = normalize_name(company_name)
    company = session.scalar(
        select(Company).where(
            Company.user_id == source.user_id,
            Company.normalized_name == normalized_company,
        )
    )
    if not company:
        company = Company(
            user_id=source.user_id,
            name=company_name,
            normalized_name=normalized_company,
        )
        session.add(company)
        session.flush()

    canonical_url = canonicalize_url(item.application_url)
    fingerprint = job_fingerprint(
        company_name=company_name,
        title=item.title,
        location=item.location,
        application_url=canonical_url,
        external_job_id=item.external_job_id,
    )
    snapshot = {
        "company_name": company_name,
        "title": item.title,
        "description_text": item.description_text,
        "description_html": item.description_html,
        "department": item.department,
        "location": item.location,
        "remote_type": item.remote_type,
        "employment_type": item.employment_type,
        "compensation_min": item.compensation_min,
        "compensation_max": item.compensation_max,
        "currency": item.currency,
        "application_url": canonical_url,
        "ats_type": item.ats_type,
        "external_job_id": item.external_job_id,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }
    content_hash = stable_hash(snapshot)

    job = session.scalar(
        select(Job).where(Job.user_id == source.user_id, Job.fingerprint == fingerprint)
    )
    matched_via_merge = False
    if job is not None and job.status == "merged":
        survivor = _resolve_merge_target(session, job)
        if survivor is not None:
            job = survivor
            matched_via_merge = True
        else:
            # No reachable survivor (the FK is `ondelete=SET NULL`, so deleting a
            # survivor orphans its tombstones). The tombstone is the only remaining
            # record of this posting and it still owns the fingerprint, so revive it
            # rather than attempt an insert that violates `uq_jobs_user_fingerprint`.
            job.merged_into_job_id = None
    if not job and item.ats_type and item.external_job_id:
        job = session.scalar(
            select(Job).where(
                Job.user_id == source.user_id,
                Job.ats_type == item.ats_type,
                Job.external_job_id == item.external_job_id,
                Job.status == "active",
            )
        )
    created = False
    updated = False
    version_is_material = False
    if not job:
        fuzzy_match = _find_fuzzy_candidate(
            session, source.user_id, company_name, item.title, item.location
        )
        job = Job(
            user_id=source.user_id,
            company_id=company.id,
            title=item.title,
            normalized_title=normalize_title(item.title),
            description_text=item.description_text,
            description_html=item.description_html,
            department=item.department,
            location=item.location,
            remote_type=item.remote_type,
            employment_type=item.employment_type,
            compensation_min=item.compensation_min,
            compensation_max=item.compensation_max,
            currency=item.currency,
            application_url=item.application_url,
            canonical_url=canonical_url,
            ats_type=item.ats_type,
            external_job_id=item.external_job_id,
            published_at=item.published_at,
            fingerprint=fingerprint,
            content_hash=content_hash,
            raw_payload=raw_payload,
        )
        session.add(job)
        session.flush()
        created = True
        if fuzzy_match is not None:
            candidate_job, scores = fuzzy_match
            _flag_fuzzy_duplicate(session, source.user_id, job, candidate_job, scores)
    else:
        job.last_seen_at = utcnow()
        job.removed_at = None
        job.status = "active"
        if job.content_hash != content_hash:
            previous_version = session.scalar(
                select(JobVersion).where(
                    JobVersion.job_id == job.id, JobVersion.content_hash == job.content_hash
                )
            )
            version_is_material = (
                previous_version is None
                or material_hash(previous_version.snapshot) != material_hash(snapshot)
            )
            if not matched_via_merge:
                # The merged-away job still owns this fingerprint and
                # `uq_jobs_user_fingerprint` is unique per user, so the survivor
                # must keep its own.
                job.fingerprint = fingerprint
            job.company_id = company.id
            job.title = item.title
            job.normalized_title = normalize_title(item.title)
            job.description_text = item.description_text
            job.description_html = item.description_html
            job.department = item.department
            job.location = item.location
            job.remote_type = item.remote_type
            job.employment_type = item.employment_type
            job.compensation_min = item.compensation_min
            job.compensation_max = item.compensation_max
            job.currency = item.currency
            job.application_url = item.application_url
            job.canonical_url = canonical_url
            job.ats_type = item.ats_type
            job.external_job_id = item.external_job_id
            job.published_at = item.published_at
            job.content_hash = content_hash
            job.raw_payload = raw_payload
            updated = True

    link = session.scalar(
        select(JobSource).where(
            JobSource.user_id == source.user_id,
            JobSource.job_id == job.id,
            JobSource.source_id == source.id,
        )
    )
    if not link:
        link = JobSource(
            user_id=source.user_id,
            job_id=job.id,
            source_id=source.id,
            source_job_url=item.source_job_url or item.application_url,
        )
        session.add(link)
    else:
        link.last_seen_at = utcnow()
        link.source_job_url = item.source_job_url or item.application_url
        link.is_active = True
        link.removed_at = None

    version = session.scalar(
        select(JobVersion).where(
            JobVersion.job_id == job.id,
            JobVersion.content_hash == content_hash,
        )
    )
    if not version:
        session.add(
            JobVersion(
                user_id=source.user_id,
                job_id=job.id,
                content_hash=content_hash,
                snapshot=snapshot,
                is_material=version_is_material,
            )
        )

    session.commit()
    return created, updated
