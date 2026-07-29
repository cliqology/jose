from conftest import _make_company, _make_job

from jose.models import JobMergeCandidate


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
