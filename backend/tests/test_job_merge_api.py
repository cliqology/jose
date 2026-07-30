import uuid

import pytest
from conftest import _make_candidate, _make_company, _make_job

from jose.api.deps import get_current_user
from jose.api.main import app


@pytest.fixture(autouse=True)
def _act_as_user(user):
    """Route client requests as the `user` fixture's user.

    `client` authenticates as the settings-configured default user
    (`get_or_create_default_user`), while `user` creates an unrelated,
    randomly-emailed user. Without this override, data created under `user`
    is invisible to requests made through `client`.
    """
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_list_job_merge_candidates_returns_job_summaries(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    _make_candidate(db_session, user, job, other)
    db_session.commit()

    response = client.get("/api/v1/job-merge-candidates")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["job"]["company_name"] == "Acme"
    assert body[0]["candidate_job"]["title"] == "Software Engineer"
    assert body[0]["matched_signals"]["company"] == 1.0


def test_resolve_dismiss_marks_candidate_dismissed(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    response = client.post(
        f"/api/v1/job-merge-candidates/{candidate.id}/resolve", json={"action": "dismiss"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


def test_resolve_merge_requires_keep(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    response = client.post(
        f"/api/v1/job-merge-candidates/{candidate.id}/resolve", json={"action": "merge"}
    )

    assert response.status_code == 400


def test_resolve_merge_then_unmerge_round_trip(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    merge_response = client.post(
        f"/api/v1/job-merge-candidates/{candidate.id}/resolve",
        json={"action": "merge", "keep": "job"},
    )
    assert merge_response.status_code == 200
    assert merge_response.json()["status"] == "merged"

    unmerge_response = client.post(f"/api/v1/job-merge-candidates/{candidate.id}/unmerge")
    assert unmerge_response.status_code == 200
    assert unmerge_response.json()["status"] == "dismissed"


def test_resolve_merge_on_stale_candidate_returns_409(client, db_session, user):
    company = _make_company(db_session, user)
    shared = _make_job(db_session, user, company)
    first_other = _make_job(
        db_session, user, company, application_url="https://acme.example.com/2"
    )
    second_other = _make_job(
        db_session, user, company, application_url="https://acme.example.com/3"
    )
    first_candidate = _make_candidate(db_session, user, first_other, shared)
    second_candidate = _make_candidate(db_session, user, second_other, shared)
    db_session.commit()

    first = client.post(
        f"/api/v1/job-merge-candidates/{first_candidate.id}/resolve",
        json={"action": "merge", "keep": "job"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/job-merge-candidates/{second_candidate.id}/resolve",
        json={"action": "merge", "keep": "job"},
    )
    assert second.status_code == 409


def test_resolve_unknown_candidate_returns_404(client):
    response = client.post(
        f"/api/v1/job-merge-candidates/{uuid.uuid4()}/resolve", json={"action": "dismiss"}
    )
    assert response.status_code == 404
