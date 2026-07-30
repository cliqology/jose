import uuid

import pytest
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


def _collect_two_titles(db_session, user, monkeypatch, title_a, title_b, company="Acme"):
    """Collect two jobs at the same company/location from two sources."""
    first_source = create_source(
        db_session,
        user,
        SourceCreate(name=f"{company} board", url=f"https://{uuid.uuid4().hex}.example.com"),
    )
    first = CollectedJob(
        company_name=company,
        title=title_a,
        location="San Francisco, CA",
        application_url=f"https://{uuid.uuid4().hex}.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([first]),
    )
    collect_source(db_session, first_source.id)

    second_source = create_source(
        db_session,
        user,
        SourceCreate(name=f"{company} board 2", url=f"https://{uuid.uuid4().hex}.example.com"),
    )
    second = CollectedJob(
        company_name=company,
        title=title_b,
        location="San Francisco, CA",
        application_url=f"https://{uuid.uuid4().hex}.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([second]),
    )
    collect_source(db_session, second_source.id)


@pytest.mark.parametrize(
    ("title_a", "title_b"),
    [
        ("Product Manager", "Product Marketing Manager"),
        ("Research Scientist", "Research Engineer"),
    ],
)
def test_distinct_roles_at_same_company_create_no_candidate(
    db_session, user, monkeypatch, title_a, title_b
):
    _collect_two_titles(db_session, user, monkeypatch, title_a, title_b)

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert candidates == []


def test_same_role_retitling_at_same_company_creates_candidate(db_session, user, monkeypatch):
    _collect_two_titles(db_session, user, monkeypatch, "Software Engineer", "Software Engineer II")

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert len(candidates) == 1
    assert candidates[0].status == "pending"


def test_best_of_two_competing_fuzzy_candidates_is_chosen(db_session, user, monkeypatch):
    """Two existing jobs both clear the thresholds; only the closest is proposed."""
    weaker_source = create_source(
        db_session, user, SourceCreate(name="Acme A", url="https://acme-a.example.com")
    )
    weaker = CollectedJob(
        company_name="Acme",
        title="Software Engineer II",
        location="New York, NY",
        application_url="https://acme-a.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([weaker]),
    )
    collect_source(db_session, weaker_source.id)

    stronger_source = create_source(
        db_session, user, SourceCreate(name="Acme B", url="https://acme-b.example.com")
    )
    stronger = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://acme-b.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([stronger]),
    )
    collect_source(db_session, stronger_source.id)

    # The second collection proposes one pairing already; resolve it so the third
    # collection starts from a clean queue with two active jobs in scope.
    for existing in db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all():
        existing.status = "dismissed"
    db_session.commit()

    weaker_job = db_session.scalar(select(Job).where(Job.title == "Software Engineer II"))
    stronger_job = db_session.scalar(
        select(Job).where(Job.user_id == user.id, Job.title == "Software Engineer")
    )
    assert weaker_job is not None and stronger_job is not None

    third_source = create_source(
        db_session, user, SourceCreate(name="Acme C", url="https://acme-c.example.com")
    )
    incoming = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://acme-c.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([incoming]),
    )
    collect_source(db_session, third_source.id)

    new_candidates = db_session.scalars(
        select(JobMergeCandidate).where(
            JobMergeCandidate.user_id == user.id, JobMergeCandidate.status == "pending"
        )
    ).all()
    assert len(new_candidates) == 1
    # Identical title and location beat the weaker title/location match.
    assert new_candidates[0].candidate_job_id == stronger_job.id
    assert new_candidates[0].candidate_job_id != weaker_job.id


def test_recollecting_merged_away_job_updates_survivor_not_tombstone(
    db_session, user, monkeypatch
):
    from jose.models import JobSource
    from jose.services.job_merge import merge_candidate

    first_source = create_source(
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
    collect_source(db_session, first_source.id)

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

    candidate = db_session.scalar(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    )
    assert candidate is not None

    # `candidate.job_id` is the newly collected job (from second_source), so keeping
    # "candidate" tombstones it and keeps the first_source job as the survivor.
    merged_away_id = candidate.job_id
    survivor_id = candidate.candidate_job_id
    merge_candidate(db_session, user, candidate.id, keep="candidate")

    survivor = db_session.get(Job, survivor_id)
    assert survivor is not None
    last_seen_before = survivor.last_seen_at

    # The merged-away job's original source re-collects the identical posting.
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([second]),
    )
    collect_source(db_session, second_source.id)

    merged_away = db_session.get(Job, merged_away_id)
    assert merged_away is not None
    db_session.refresh(merged_away)
    assert merged_away.status == "merged"
    assert merged_away.merged_into_job_id == survivor_id

    db_session.refresh(survivor)
    assert survivor.status == "active"
    assert survivor.last_seen_at > last_seen_before

    # No third job was created, and the re-collected source links only to the survivor.
    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2

    links = db_session.scalars(
        select(JobSource).where(
            JobSource.user_id == user.id, JobSource.source_id == second_source.id
        )
    ).all()
    assert len(links) == 1
    assert links[0].job_id == survivor_id


def test_recollecting_orphaned_tombstone_revives_it(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme board", url="https://acme-a.example.com")
    )
    item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://acme-a.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([item]),
    )
    collect_source(db_session, source.id)

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert job is not None
    # Orphaned tombstone: status "merged" with no reachable survivor, which is what
    # the `ondelete=SET NULL` FK leaves behind when a survivor job is deleted.
    job.status = "merged"
    job.merged_into_job_id = None
    original_fingerprint = job.fingerprint
    db_session.commit()

    collect_source(db_session, source.id)

    # Reviving the orphan is the only option that neither loses the posting nor
    # violates `uq_jobs_user_fingerprint`, which the tombstone still holds.
    db_session.refresh(job)
    assert job.status == "active"
    assert job.merged_into_job_id is None
    assert job.fingerprint == original_fingerprint
    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 1


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
