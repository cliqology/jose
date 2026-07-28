from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select

from jose.models import Source, SourceImportRun


def _workbook_bytes(rows: list[tuple[str | None, str | None]]) -> bytes:
    wb = Workbook()
    sheet = wb.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _upload(client, path: str, rows: list[tuple[str | None, str | None]]):
    content = _workbook_bytes(rows)
    return client.post(
        path,
        files={
            "file": (
                "test.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_preview_endpoint_reports_counts_without_writing(client):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Api Preview Co", "https://api-preview-only.example.com"),
    ]
    response = _upload(client, "/api/v1/sources/import/preview", rows)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 1
    assert body["updated"] == 0

    follow_up = client.get("/api/v1/sources")
    urls = [s["url"] for s in follow_up.json()]
    assert "https://api-preview-only.example.com" not in urls


def test_commit_endpoint_creates_sources_and_retains_report(client, db_session):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Api Commit Co", "https://api-commit.example.com"),
    ]
    response = _upload(client, "/api/v1/sources/import/commit", rows)
    run_id = None
    try:
        assert response.status_code == 201, response.text
        body = response.json()
        run_id = body["id"]
        assert body["created_count"] == 1
        assert body["filename"] == "test.xlsx"

        runs = client.get("/api/v1/sources/import/runs")
        assert runs.status_code == 200
        assert any(r["id"] == run_id for r in runs.json())
    finally:
        source = db_session.scalar(
            select(Source).where(Source.url == "https://api-commit.example.com")
        )
        if source:
            db_session.delete(source)
        if run_id:
            run = db_session.get(SourceImportRun, run_id)
            if run:
                db_session.delete(run)
        db_session.commit()
