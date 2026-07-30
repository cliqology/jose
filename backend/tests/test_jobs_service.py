import uuid

import pytest
from conftest import _make_company, _make_job

from jose.models import JobSource, Source
from jose.services.jobs import list_jobs


def _make_source(session, user, name="Source"):
    source = Source(user_id=user.id, name=name, url=f"https://{uuid.uuid4().hex}.example.com")
    session.add(source)
    session.flush()
    return source


def test_list_jobs_defaults_exclude_irrelevant_and_archived(db_session, user):
    company = _make_company(db_session, user)
    undecided = _make_job(db_session, user, company, application_url="https://a.example.com/1")
    applied = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/2",
        user_decision="applied",
    )
    irrelevant = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/3",
        user_decision="irrelevant",
    )
    archived = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/4",
        user_decision="archived",
    )
    db_session.commit()

    results = list_jobs(db_session, user)

    ids = {row["id"] for row in results}
    assert undecided.id in ids
    assert applied.id in ids
    assert irrelevant.id not in ids
    assert archived.id not in ids


def test_list_jobs_explicit_decision_filter_includes_hidden_defaults(db_session, user):
    company = _make_company(db_session, user)
    irrelevant = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/1",
        user_decision="irrelevant",
    )
    db_session.commit()

    results = list_jobs(db_session, user, decision=["irrelevant"])

    assert {row["id"] for row in results} == {irrelevant.id}


def test_list_jobs_filters_by_company_title_location_ats(db_session, user):
    company_a = _make_company(db_session, user, name="Acme Robotics")
    company_b = _make_company(db_session, user, name="Beta Systems")
    target = _make_job(
        db_session,
        user,
        company_a,
        title="Senior Platform Engineer",
        location="Remote - US",
        ats_type="greenhouse",
        application_url="https://a.example.com/1",
    )
    _make_job(
        db_session,
        user,
        company_b,
        title="Sales Rep",
        location="New York, NY",
        ats_type="lever",
        application_url="https://a.example.com/2",
    )
    db_session.commit()

    assert {row["id"] for row in list_jobs(db_session, user, company="acme")} == {target.id}
    assert {row["id"] for row in list_jobs(db_session, user, title="platform")} == {target.id}
    assert {row["id"] for row in list_jobs(db_session, user, location="remote")} == {target.id}
    assert {row["id"] for row in list_jobs(db_session, user, ats_type="greenhouse")} == {
        target.id
    }


def test_list_jobs_filters_by_source(db_session, user):
    company = _make_company(db_session, user)
    linked = _make_job(db_session, user, company, application_url="https://a.example.com/1")
    unlinked = _make_job(db_session, user, company, application_url="https://a.example.com/2")
    source = _make_source(db_session, user)
    db_session.add(JobSource(user_id=user.id, job_id=linked.id, source_id=source.id))
    db_session.commit()

    results = list_jobs(db_session, user, source_id=source.id)

    ids = {row["id"] for row in results}
    assert linked.id in ids
    assert unlinked.id not in ids


def test_list_jobs_filters_by_date_range(db_session, user):
    from datetime import UTC, datetime

    company = _make_company(db_session, user)
    in_range = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/1",
        first_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    out_of_range = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/2",
        first_seen_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db_session.commit()

    results = list_jobs(db_session, user, date_from="2026-07-01", date_to="2026-07-31")

    ids = {row["id"] for row in results}
    assert in_range.id in ids
    assert out_of_range.id not in ids


def test_list_jobs_pagination(db_session, user):
    company = _make_company(db_session, user)
    for i in range(3):
        _make_job(db_session, user, company, application_url=f"https://a.example.com/{i}")
    db_session.commit()

    page_one = list_jobs(db_session, user, limit=2, offset=0)
    page_two = list_jobs(db_session, user, limit=2, offset=2)

    assert len(page_one) == 2
    assert len(page_two) == 1


def test_list_jobs_isolates_by_user(db_session, user, other_user):
    company = _make_company(db_session, user)
    _make_job(db_session, user, company, application_url="https://a.example.com/1")
    other_company = _make_company(db_session, other_user)
    _make_job(db_session, other_user, other_company, application_url="https://b.example.com/1")
    db_session.commit()

    results = list_jobs(db_session, user)

    assert len(results) == 1


def test_get_job_detail_includes_sources_and_versions(db_session, user):
    from jose.models import JobSource, JobVersion
    from jose.services.jobs import get_job_detail

    company = _make_company(db_session, user)
    job = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/1",
        description_text="Build things.",
    )
    source = _make_source(db_session, user, name="Acme Careers")
    db_session.add(
        JobSource(
            user_id=user.id,
            job_id=job.id,
            source_id=source.id,
            source_job_url="https://acme.example.com/jobs/1",
            is_active=True,
        )
    )
    db_session.add(
        JobVersion(
            user_id=user.id,
            job_id=job.id,
            content_hash="hash-1",
            snapshot={"title": job.title},
            is_material=True,
        )
    )
    db_session.commit()

    detail = get_job_detail(db_session, user, job.id)

    assert detail["id"] == job.id
    assert detail["company_name"] == company.name
    assert detail["description_text"] == "Build things."
    assert len(detail["sources"]) == 1
    assert detail["sources"][0]["source_name"] == "Acme Careers"
    assert detail["sources"][0]["source_job_url"] == "https://acme.example.com/jobs/1"
    assert len(detail["versions"]) == 1
    assert detail["versions"][0]["content_hash"] == "hash-1"


def test_get_job_detail_raises_for_missing_job(db_session, user):
    import uuid

    from jose.services.jobs import JobNotFoundError, get_job_detail

    with pytest.raises(JobNotFoundError):
        get_job_detail(db_session, user, uuid.uuid4())


def test_get_job_detail_rejects_other_user(db_session, user, other_user):
    from jose.services.jobs import JobNotFoundError, get_job_detail

    company = _make_company(db_session, other_user)
    job = _make_job(db_session, other_user, company, application_url="https://a.example.com/1")
    db_session.commit()

    with pytest.raises(JobNotFoundError):
        get_job_detail(db_session, user, job.id)
