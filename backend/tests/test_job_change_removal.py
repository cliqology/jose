from conftest import _make_company, _make_job
from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.models import Job, JobSource, JobVersion, Source
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
