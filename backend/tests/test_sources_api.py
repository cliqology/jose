import uuid

from jose.models import Source


def _create(client, url="https://api-test.example.com/careers", **overrides):
    payload = {"name": "API Test Source", "url": url, **overrides}
    response = client.post("/api/v1/sources", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _cleanup(db_session, source_id: str) -> None:
    source = db_session.get(Source, uuid.UUID(source_id))
    if source:
        db_session.delete(source)
        db_session.commit()


def test_get_source_returns_created_source(client, db_session):
    created = _create(client, url="https://api-get.example.com")
    try:
        response = client.get(f"/api/v1/sources/{created['id']}")
        assert response.status_code == 200
        assert response.json()["name"] == "API Test Source"
    finally:
        _cleanup(db_session, created["id"])


def test_get_unknown_source_returns_404(client):
    response = client.get(f"/api/v1/sources/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_duplicate_url_returns_409(client, db_session):
    created = _create(client, url="https://api-dup.example.com/careers")
    try:
        response = client.post(
            "/api/v1/sources",
            json={"name": "Dup", "url": "https://api-dup.example.com/careers"},
        )
        assert response.status_code == 409
    finally:
        _cleanup(db_session, created["id"])


def test_create_invalid_category_returns_422(client):
    response = client.post(
        "/api/v1/sources",
        json={"name": "Bad", "url": "https://bad-category.example.com", "category": "nonsense"},
    )
    assert response.status_code == 422


def test_create_priority_out_of_range_returns_422(client):
    response = client.post(
        "/api/v1/sources",
        json={"name": "Bad", "url": "https://bad-priority.example.com", "priority": 0},
    )
    assert response.status_code == 422


def test_patch_updates_source(client, db_session):
    created = _create(client, url="https://api-patch.example.com")
    try:
        response = client.patch(
            f"/api/v1/sources/{created['id']}", json={"enabled": False, "priority": 3}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["priority"] == 3
    finally:
        _cleanup(db_session, created["id"])


def test_delete_without_confirm_returns_400(client, db_session):
    created = _create(client, url="https://api-delete-noconfirm.example.com")
    try:
        response = client.delete(f"/api/v1/sources/{created['id']}")
        assert response.status_code == 400
    finally:
        _cleanup(db_session, created["id"])


def test_delete_with_confirm_returns_204(client):
    created = _create(client, url="https://api-delete-confirmed.example.com")
    response = client.delete(f"/api/v1/sources/{created['id']}?confirm=true")
    assert response.status_code == 204
    follow_up = client.get(f"/api/v1/sources/{created['id']}")
    assert follow_up.status_code == 404


def test_source_read_includes_consecutive_failures(client, db_session):
    created = _create(client, url="https://api-consecutive.example.com")
    try:
        assert created["consecutive_failures"] == 0
    finally:
        _cleanup(db_session, created["id"])


def test_list_source_runs_empty(client, db_session):
    created = _create(client, url="https://api-runs-empty.example.com")
    try:
        response = client.get(f"/api/v1/sources/{created['id']}/runs")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        _cleanup(db_session, created["id"])


def test_list_source_runs_returns_newest_first_and_respects_limit(client, db_session):
    from datetime import timedelta

    from jose.models import Source, SourceRun
    from jose.models.base import utcnow

    created = _create(client, url="https://api-runs-order.example.com")
    try:
        source = db_session.get(Source, uuid.UUID(created["id"]))
        base = utcnow()
        for i in range(25):
            db_session.add(
                SourceRun(
                    user_id=source.user_id,
                    source_id=source.id,
                    status="success",
                    started_at=base + timedelta(seconds=i),
                    jobs_found=i,
                )
            )
        db_session.commit()

        response = client.get(f"/api/v1/sources/{created['id']}/runs")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 20
        assert body[0]["jobs_found"] == 24
    finally:
        _cleanup(db_session, created["id"])


def test_list_source_runs_unknown_source_returns_404(client):
    response = client.get(f"/api/v1/sources/{uuid.uuid4()}/runs")
    assert response.status_code == 404
