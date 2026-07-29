import uuid

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


def test_fuzzy_company_alias_creates_pending_merge_candidate(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="OpenAI board", url="https://openai-a.example.com")
    )
    first = CollectedJob(
        company_name="OpenAI",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-a.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([first]),
    )
    collect_source(db_session, source.id)

    second_source = create_source(
        db_session, user, SourceCreate(name="OpenAI board 2", url="https://openai-b.example.com")
    )
    second = CollectedJob(
        company_name="OpenAI, Inc.",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-b.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([second]),
    )
    collect_source(db_session, second_source.id)

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert len(candidates) == 1
    assert candidates[0].status == "pending"
    assert candidates[0].matched_signals["company"] >= 0.6


def test_fuzzy_match_below_threshold_creates_no_candidate(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme board", url="https://acme-a.example.com")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Backend Engineer",
        location="San Francisco, CA",
        application_url="https://acme-a.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([first]),
    )
    collect_source(db_session, source.id)

    second_source = create_source(
        db_session, user, SourceCreate(name="Acme board 2", url="https://acme-b.example.com")
    )
    second = CollectedJob(
        company_name="Acme",
        title="Enterprise Sales Director",
        location="San Francisco, CA",
        application_url="https://acme-b.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([second]),
    )
    collect_source(db_session, second_source.id)

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert candidates == []


def test_dismissed_pair_is_not_reproposed(db_session, user):
    from jose.services.collection import _flag_fuzzy_duplicate

    company = _make_company(db_session, user, name="Acme")
    job_a = _make_job(db_session, user, company, application_url="https://acme.example.com/a")
    job_b = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/b",
        fingerprint=uuid.uuid4().hex,
    )
    scores = {"company": 1.0, "title": 1.0, "location": 1.0, "composite": 1.0}

    first_candidate = _flag_fuzzy_duplicate(db_session, user.id, job_b, job_a, scores)
    db_session.commit()
    assert first_candidate is not None

    first_candidate.status = "dismissed"
    db_session.commit()

    second_candidate = _flag_fuzzy_duplicate(db_session, user.id, job_b, job_a, scores)
    db_session.commit()
    assert second_candidate is None

    all_candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert len(all_candidates) == 1
