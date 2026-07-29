from conftest import _make_company, _make_job
from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.models import Job, JobMergeCandidate
from jose.schemas import SourceCreate
from jose.services.collection import collect_source
from jose.services.sources import create_source


def test_job_merged_into_job_id_defaults_to_none(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    db_session.commit()

    assert job.merged_into_job_id is None
    assert job.status == "active"


def test_job_merge_candidate_persists_fields(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company, application_url="https://acme.example.com/jobs/1")
    candidate_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/jobs/2"
    )

    candidate = JobMergeCandidate(
        user_id=user.id,
        job_id=job.id,
        candidate_job_id=candidate_job.id,
        similarity_score=0.9,
        matched_signals={"company": 1.0, "title": 1.0, "location": 0.5},
        status="pending",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    assert candidate.id is not None
    assert candidate.status == "pending"
    assert candidate.resolved_at is None
    assert candidate.matched_signals == {"company": 1.0, "title": 1.0, "location": 0.5}
    assert candidate.moved_job_source_ids == []
    assert candidate.moved_job_version_ids == []


class _FakeCollector:
    def __init__(self, jobs):
        self._jobs = jobs

    def collect(self, source_name, source_url):
        return CollectionResult(jobs=self._jobs)


def test_ats_job_id_match_updates_same_job_despite_title_change(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-ats.example.com/jobs")
    )
    first_job = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-ats.example.com/apply/1",
        ats_type="greenhouse",
        external_job_id="gh-42",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([first_job]),
    )
    collect_source(db_session, source.id)

    retitled_job = CollectedJob(
        company_name="Acme",
        title="Senior Software Engineer",
        application_url="https://acme-ats.example.com/apply/1-v2",
        ats_type="greenhouse",
        external_job_id="gh-42",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([retitled_job]),
    )
    collect_source(db_session, source.id)

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 1
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].external_job_id == "gh-42"
