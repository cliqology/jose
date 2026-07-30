import pytest
from conftest import _make_company, _make_job
from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.models import Job, JobMergeCandidate, JobSource, JobVersion, Source
from jose.schemas import SourceCreate
from jose.services.collection import collect_source
from jose.services.sources import create_source


def test_job_source_defaults_to_active(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    source = Source(
        user_id=user.id,
        name="Test Source",
        url="https://example.com",
    )
    db_session.add(source)
    db_session.flush()

    link = JobSource(user_id=user.id, job_id=job.id, source_id=source.id)
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    assert link.is_active is True
    assert link.removed_at is None


def test_job_reposted_from_job_id_defaults_to_none(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)

    assert job.reposted_from_job_id is None


def test_job_version_defaults_to_material(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    version = JobVersion(user_id=user.id, job_id=job.id, content_hash="hash-1", snapshot={"a": 1})
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)

    assert version.is_material is True


class _FakeCollector:
    def __init__(self, jobs):
        self._jobs = jobs

    def collect(self, source_name, source_url):
        return CollectionResult(jobs=self._jobs)


def _collect(monkeypatch, db_session, source, jobs):
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector(jobs),
    )
    return collect_source(db_session, source.id)


def test_formatting_only_description_change_is_not_material(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-mat.example.com/jobs")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat.example.com/apply/1",
        description_html="<p>Build great things.</p>",
    )
    _collect(monkeypatch, db_session, source, [first])

    reformatted = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat.example.com/apply/1",
        description_html="<div><p>Build   great things.</p></div>",
    )
    _collect(monkeypatch, db_session, source, [reformatted])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    versions = db_session.scalars(
        select(JobVersion).where(JobVersion.job_id == job.id).order_by(JobVersion.seen_at)
    ).all()
    assert len(versions) == 2
    assert versions[1].is_material is False


def test_compensation_change_is_material(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-mat2.example.com/jobs")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat2.example.com/apply/1",
        compensation_min=150000,
    )
    _collect(monkeypatch, db_session, source, [first])

    raised = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat2.example.com/apply/1",
        compensation_min=160000,
    )
    _collect(monkeypatch, db_session, source, [raised])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    versions = db_session.scalars(
        select(JobVersion).where(JobVersion.job_id == job.id).order_by(JobVersion.seen_at)
    ).all()
    assert len(versions) == 2
    assert versions[1].is_material is True


def test_new_job_first_version_is_not_counted_as_a_change(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-mat3.example.com/jobs")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat3.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [first])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    version = db_session.scalar(select(JobVersion).where(JobVersion.job_id == job.id))
    assert version.is_material is False


def test_job_source_link_goes_inactive_when_absent_from_next_successful_run(
    db_session, user, monkeypatch
):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-sweep1.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep1.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [job_item])
    _collect(monkeypatch, db_session, source, [])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    link = db_session.scalar(select(JobSource).where(JobSource.job_id == job.id))

    assert link.is_active is False
    assert link.removed_at is not None
    assert job.status == "removed"
    assert job.removed_at is not None


def test_job_stays_active_when_a_second_source_still_lists_it(db_session, user, monkeypatch):
    source_a = create_source(
        db_session, user, SourceCreate(name="Acme A", url="https://acme-sweep2a.example.com/jobs")
    )
    source_b = create_source(
        db_session, user, SourceCreate(name="Acme B", url="https://acme-sweep2b.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep2.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source_a, [job_item])
    _collect(monkeypatch, db_session, source_b, [job_item])

    _collect(monkeypatch, db_session, source_a, [])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert job.status == "active"

    link_a = db_session.scalar(
        select(JobSource).where(JobSource.job_id == job.id, JobSource.source_id == source_a.id)
    )
    link_b = db_session.scalar(
        select(JobSource).where(JobSource.job_id == job.id, JobSource.source_id == source_b.id)
    )
    assert link_a.is_active is False
    assert link_b.is_active is True


def test_failed_run_leaves_job_source_state_untouched(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-sweep3.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep3.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [job_item])

    class _FailingCollector:
        def collect(self, source_name, source_url):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector(),
    )
    with pytest.raises(RuntimeError):
        collect_source(db_session, source.id)

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    link = db_session.scalar(select(JobSource).where(JobSource.job_id == job.id))
    assert job.status == "active"
    assert link.is_active is True


def test_revival_reactivates_job_and_link(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-sweep4.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep4.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [job_item])
    _collect(monkeypatch, db_session, source, [])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert job.status == "removed"

    _collect(monkeypatch, db_session, source, [job_item])

    db_session.refresh(job)
    link = db_session.scalar(select(JobSource).where(JobSource.job_id == job.id))
    assert job.status == "active"
    assert job.removed_at is None
    assert link.is_active is True
    assert link.removed_at is None


def test_repost_linked_to_removed_job_above_threshold(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-repost1.example.com/jobs")
    )
    original = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://acme-repost1.example.com/apply/1",
        ats_type="greenhouse",
        external_job_id="gh-100",
    )
    _collect(monkeypatch, db_session, source, [original])
    _collect(monkeypatch, db_session, source, [])

    removed_job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert removed_job.status == "removed"

    reposted = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://acme-repost1.example.com/apply/1-repost",
        ats_type="greenhouse",
        external_job_id="gh-200",
    )
    _collect(monkeypatch, db_session, source, [reposted])

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2
    new_job = next(j for j in jobs if j.id != removed_job.id)
    assert new_job.reposted_from_job_id == removed_job.id


def test_repost_not_linked_below_threshold(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-repost2.example.com/jobs")
    )
    original = CollectedJob(
        company_name="Acme",
        title="Backend Engineer",
        location="San Francisco, CA",
        application_url="https://acme-repost2.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [original])
    _collect(monkeypatch, db_session, source, [])

    removed_job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert removed_job.status == "removed"

    unrelated = CollectedJob(
        company_name="Acme",
        title="Enterprise Sales Director",
        location="San Francisco, CA",
        application_url="https://acme-repost2.example.com/apply/2",
    )
    _collect(monkeypatch, db_session, source, [unrelated])

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2
    new_job = next(j for j in jobs if j.id != removed_job.id)
    assert new_job.reposted_from_job_id is None


def test_active_fuzzy_match_uses_merge_queue_not_repost_link(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="OpenAI board", url="https://openai-repost-a.example.com")
    )
    first = CollectedJob(
        company_name="OpenAI",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-repost-a.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [first])

    second_source = create_source(
        db_session, user, SourceCreate(name="OpenAI board 2", url="https://openai-repost-b.example.com")
    )
    second = CollectedJob(
        company_name="OpenAI, Inc.",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-repost-b.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, second_source, [second])

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2
    assert all(job.reposted_from_job_id is None for job in jobs)

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert len(candidates) == 1
