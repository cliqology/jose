import uuid

from jose.models import JobSource, JobVersion, Source

from conftest import _make_company, _make_job


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
