import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from jose.collectors import get_collector
from jose.collectors.base import CollectedJob
from jose.collectors.utils import (
    canonicalize_url,
    job_fingerprint,
    normalize_name,
    normalize_title,
    stable_hash,
)
from jose.config import get_settings
from jose.models import Company, Job, JobSource, JobVersion, Source, SourceRun


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
    if not job:
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
    else:
        job.last_seen_at = utcnow()
        job.removed_at = None
        job.status = "active"
        if job.content_hash != content_hash:
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
            )
        )

    session.commit()
    return created, updated
