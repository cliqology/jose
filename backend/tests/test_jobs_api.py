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


def test_dashboard_summary_excludes_merged_away_changed_and_reposted_jobs(db_session, user):
    from jose.models import JobVersion

    company = _make_company(db_session, user)

    changed_and_merged = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/changed-merged",
        status="merged",
    )
    db_session.add(
        JobVersion(
            user_id=user.id,
            job_id=changed_and_merged.id,
            content_hash="hash-changed-merged",
            snapshot={"a": 1},
            is_material=True,
        )
    )

    original_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/original-2"
    )
    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/repost-merged",
        reposted_from_job_id=original_job.id,
        status="merged",
    )
    db_session.commit()

    summary = get_dashboard_summary(db_session, user)

    assert summary.jobs_changed_last_24h == 0
    assert summary.jobs_reposted_last_24h == 0


def test_dashboard_summary_excludes_rows_outside_24h_window(db_session, user):
    """Every job's `first_seen_at` is set explicitly (inside or outside the window)
    so the `jobs_new_last_24h` count doesn't pick up rows meant only to exercise
    the changed/removed/reposted boundaries.
    """
    from datetime import UTC, datetime, timedelta

    from jose.models import JobVersion

    company = _make_company(db_session, user)
    now = datetime.now(UTC)
    inside = now - timedelta(hours=1)
    outside = now - timedelta(hours=25)

    # --- inside-window rows: one of each kind, each expected to count. ---
    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/new-in",
        first_seen_at=inside,
    )

    changed_in = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/changed-in",
        first_seen_at=outside,  # not itself "new"; only the version matters here
    )
    db_session.add(
        JobVersion(
            user_id=user.id,
            job_id=changed_in.id,
            content_hash="hash-changed-in",
            snapshot={"a": 1},
            is_material=True,
            seen_at=inside,
        )
    )

    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/removed-in",
        first_seen_at=outside,
        status="removed",
        removed_at=inside,
    )

    original_in = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/original-in",
        first_seen_at=outside,
    )
    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/repost-in",
        reposted_from_job_id=original_in.id,
        first_seen_at=inside,
    )

    # --- outside-window rows: one of each kind, none expected to count. ---
    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/new-out",
        first_seen_at=outside,
    )

    changed_out = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/changed-out",
        first_seen_at=outside,
    )
    db_session.add(
        JobVersion(
            user_id=user.id,
            job_id=changed_out.id,
            content_hash="hash-changed-out",
            snapshot={"a": 1},
            is_material=True,
            seen_at=outside,
        )
    )

    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/removed-out",
        first_seen_at=outside,
        status="removed",
        removed_at=outside,
    )

    original_out = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/original-out",
        first_seen_at=outside,
    )
    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/repost-out",
        reposted_from_job_id=original_out.id,
        first_seen_at=outside,
    )
    db_session.commit()

    summary = get_dashboard_summary(db_session, user)

    # Only the inside-window rows are counted: the "new" job plus the repost
    # job (whose own first_seen_at also falls inside the window).
    assert summary.jobs_new_last_24h == 2
    assert summary.jobs_changed_last_24h == 1
    assert summary.jobs_removed_last_24h == 1
    assert summary.jobs_reposted_last_24h == 1
