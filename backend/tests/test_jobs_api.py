import pytest
from conftest import _make_company, _make_job

from jose.api.deps import get_current_user
from jose.api.main import app
from jose.services.dashboard import get_dashboard_summary


@pytest.fixture(autouse=True)
def _act_as_user(user):
    """Route client requests as the `user` fixture's user."""
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _active_and_merged_jobs(db_session, user):
    company = _make_company(db_session, user)
    active = _make_job(
        db_session, user, company, title="Kept Role", application_url="https://acme.example.com/1"
    )
    merged = _make_job(
        db_session,
        user,
        company,
        title="Merged Away Role",
        application_url="https://acme.example.com/2",
        status="merged",
    )
    merged.merged_into_job_id = active.id
    db_session.commit()
    return active, merged


def test_list_jobs_excludes_merged_away_jobs(client, db_session, user):
    active, merged = _active_and_merged_jobs(db_session, user)

    response = client.get("/api/v1/jobs")

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()}
    assert str(active.id) in returned_ids
    assert str(merged.id) not in returned_ids


def test_dashboard_summary_excludes_merged_away_jobs(db_session, user):
    _active_and_merged_jobs(db_session, user)

    summary = get_dashboard_summary(db_session, user)

    assert summary.jobs_total == 1
    assert summary.jobs_seen_last_24h == 1


def test_list_jobs_includes_reposted_from_job_id(client, db_session, user):
    company = _make_company(db_session, user)
    original = _make_job(
        db_session, user, company, application_url="https://acme.example.com/1", status="removed"
    )
    repost = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/2",
        reposted_from_job_id=original.id,
    )
    db_session.commit()

    response = client.get("/api/v1/jobs")

    assert response.status_code == 200
    body = {item["id"]: item for item in response.json()}
    assert body[str(repost.id)]["reposted_from_job_id"] == str(original.id)


def test_dashboard_summary_new_changed_removed_reposted_counts(db_session, user):
    from datetime import UTC, datetime

    from jose.models import JobVersion

    company = _make_company(db_session, user)

    _make_job(db_session, user, company, application_url="https://acme.example.com/new")

    changed_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/changed"
    )
    db_session.add(
        JobVersion(
            user_id=user.id,
            job_id=changed_job.id,
            content_hash="hash-changed",
            snapshot={"a": 1},
            is_material=True,
        )
    )

    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/removed",
        status="removed",
        removed_at=datetime.now(UTC),
    )

    original_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/original"
    )
    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/repost",
        reposted_from_job_id=original_job.id,
    )
    db_session.commit()

    summary = get_dashboard_summary(db_session, user)

    assert summary.jobs_new_last_24h == 5
    assert summary.jobs_changed_last_24h == 1
    assert summary.jobs_removed_last_24h == 1
    assert summary.jobs_reposted_last_24h == 1
