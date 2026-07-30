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
