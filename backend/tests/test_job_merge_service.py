import uuid

import pytest
from conftest import _make_candidate, _make_company, _make_job
from sqlalchemy import select

from jose.models import JobSource, JobVersion, SystemEvent
from jose.services.job_merge import (
    MergeCandidateNotFoundError,
    MergeCandidateNotMergedError,
    MergeCandidateNotPendingError,
    dismiss_merge_candidate,
    list_merge_candidates,
    merge_candidate,
    unmerge_candidate,
)


def _make_source(session, user, name="Source"):
    from jose.models import Source

    source = Source(user_id=user.id, name=name, url=f"https://{uuid.uuid4().hex}.example.com")
    session.add(source)
    session.flush()
    return source


def test_list_merge_candidates_filters_by_status_and_user(db_session, user, other_user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other_job = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    _make_candidate(db_session, user, job, other_job)

    other_company = _make_company(db_session, other_user, name="Other Co")
    other_user_job = _make_job(db_session, other_user, other_company)
    other_user_job_2 = _make_job(
        db_session, other_user, other_company, application_url="https://other.example.com/2"
    )
    _make_candidate(db_session, other_user, other_user_job, other_user_job_2)
    db_session.commit()

    results = list_merge_candidates(db_session, user)
    assert len(results) == 1
    assert results[0].user_id == user.id


def test_dismiss_merge_candidate_marks_dismissed(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    result = dismiss_merge_candidate(db_session, user, candidate.id)

    assert result.status == "dismissed"
    assert result.resolved_at is not None


def test_dismiss_already_resolved_candidate_raises(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other, status="dismissed")
    db_session.commit()

    with pytest.raises(MergeCandidateNotPendingError):
        dismiss_merge_candidate(db_session, user, candidate.id)


def test_merge_candidate_unknown_id_raises(db_session, user):
    with pytest.raises(MergeCandidateNotFoundError):
        dismiss_merge_candidate(db_session, user, uuid.uuid4())


def test_merge_reassigns_job_sources_and_versions(db_session, user):
    company = _make_company(db_session, user)
    kept_job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    merged_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/2"
    )

    source = _make_source(db_session, user)
    merged_source_link = JobSource(
        user_id=user.id, job_id=merged_job.id, source_id=source.id, source_job_url="x"
    )
    merged_version = JobVersion(
        user_id=user.id, job_id=merged_job.id, content_hash="hash-1", snapshot={"a": 1}
    )
    db_session.add_all([merged_source_link, merged_version])
    candidate = _make_candidate(db_session, user, kept_job, merged_job)
    db_session.commit()

    result = merge_candidate(db_session, user, candidate.id, keep="job")

    assert result.status == "merged"
    assert result.kept_job_id == kept_job.id
    assert result.merged_job_id == merged_job.id

    db_session.refresh(merged_job)
    assert merged_job.status == "merged"
    assert merged_job.merged_into_job_id == kept_job.id

    db_session.refresh(merged_source_link)
    assert merged_source_link.job_id == kept_job.id
    db_session.refresh(merged_version)
    assert merged_version.job_id == kept_job.id

    events = db_session.scalars(
        select(SystemEvent).where(SystemEvent.event_type == "job_merged")
    ).all()
    assert len(events) == 1
    assert events[0].entity_id == kept_job.id


def test_merge_link_collision_keeps_more_recently_seen(db_session, user):
    from datetime import UTC, datetime, timedelta

    company = _make_company(db_session, user)
    kept_job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    merged_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/2"
    )
    shared_source_id = _make_source(db_session, user).id
    now = datetime.now(UTC)

    kept_link = JobSource(
        user_id=user.id,
        job_id=kept_job.id,
        source_id=shared_source_id,
        source_job_url="old",
        last_seen_at=now - timedelta(days=1),
    )
    merged_link = JobSource(
        user_id=user.id,
        job_id=merged_job.id,
        source_id=shared_source_id,
        source_job_url="new",
        last_seen_at=now,
    )
    db_session.add_all([kept_link, merged_link])
    candidate = _make_candidate(db_session, user, kept_job, merged_job)
    db_session.commit()

    merge_candidate(db_session, user, candidate.id, keep="job")

    links = db_session.scalars(
        select(JobSource).where(
            JobSource.user_id == user.id, JobSource.source_id == shared_source_id
        )
    ).all()
    assert len(links) == 1
    assert links[0].job_id == kept_job.id
    assert links[0].source_job_url == "new"


def test_unmerge_restores_only_originally_moved_rows(db_session, user):
    company = _make_company(db_session, user)
    kept_job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    merged_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/2"
    )
    original_source = _make_source(db_session, user, name="Original Source")
    original_link = JobSource(
        user_id=user.id,
        job_id=merged_job.id,
        source_id=original_source.id,
        source_job_url="original",
    )
    db_session.add(original_link)
    candidate = _make_candidate(db_session, user, kept_job, merged_job)
    db_session.commit()

    merge_candidate(db_session, user, candidate.id, keep="job")

    later_source = _make_source(db_session, user, name="Later Source")
    later_link = JobSource(
        user_id=user.id, job_id=kept_job.id, source_id=later_source.id, source_job_url="later"
    )
    db_session.add(later_link)
    db_session.commit()

    result = unmerge_candidate(db_session, user, candidate.id)

    assert result.status == "dismissed"
    db_session.refresh(merged_job)
    assert merged_job.status == "active"
    assert merged_job.merged_into_job_id is None

    db_session.refresh(original_link)
    assert original_link.job_id == merged_job.id
    db_session.refresh(later_link)
    assert later_link.job_id == kept_job.id

    events = db_session.scalars(
        select(SystemEvent).where(SystemEvent.event_type == "job_unmerged")
    ).all()
    assert len(events) == 1


def test_unmerge_requires_merged_status(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    with pytest.raises(MergeCandidateNotMergedError):
        unmerge_candidate(db_session, user, candidate.id)
