from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select

from jose.models import Source, SourceImportRun
from jose.services.source_import import classify_workbook, commit_import


def _workbook(rows: list[tuple[str | None, str | None]]) -> BytesIO:
    wb = Workbook()
    sheet = wb.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def test_classify_does_not_write_to_the_database(db_session, user):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Acme Ventures", "https://preview-only.example.com"),
    ]
    classify_workbook(db_session, user, _workbook(rows))

    found = db_session.scalar(
        select(Source).where(Source.url == "https://preview-only.example.com")
    )
    assert found is None


def test_classify_maps_section_headers_to_categories(db_session, user):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Acme Ventures", "https://jobs.acme.example.com/careers"),
        ("JOBS NEWSLETTERS", None),
        ("NEWSLETTER", "URL"),
        ("Weekly Exec Jobs", "https://weeklyexec.example.com"),
        ("VC FELLOWSHIPS / TALENT NETWORKS", None),
        ("NETWORK / PROGRAM", "URL"),
        ("Founder Fellows", "https://founderfellows.example.com"),
    ]
    outcomes = classify_workbook(db_session, user, _workbook(rows))

    by_url = {o.url: o for o in outcomes if o.action != "skip"}
    assert by_url["https://jobs.acme.example.com/careers"].category == "vc_portfolio"
    assert by_url["https://weeklyexec.example.com"].category == "newsletter"
    assert by_url["https://founderfellows.example.com"].category == "talent_network"


def test_classify_skips_blank_and_header_rows(db_session, user):
    rows = [
        (None, None),
        ("VC FIRM", "JOB AGGREGATOR URL"),
        (None, None),
        ("Acme Ventures", "https://skip-test.example.com/careers"),
    ]
    outcomes = classify_workbook(db_session, user, _workbook(rows))

    skipped = [o for o in outcomes if o.action == "skip"]
    assert len(skipped) == 2


def test_classify_flags_duplicate_url_within_workbook(db_session, user):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Acme Ventures", "https://dup-in-sheet.example.com"),
        ("Acme Ventures Again", "https://dup-in-sheet.example.com"),
    ]
    outcomes = classify_workbook(db_session, user, _workbook(rows))
    actionable = [o for o in outcomes if o.action != "skip"]

    assert [o.action for o in actionable] == ["create", "flag"]
    assert "duplicate" in actionable[1].reason.lower()


def test_classify_flags_url_before_any_section_header(db_session, user):
    rows = [("Mystery Co", "https://no-section-yet.example.com")]
    outcomes = classify_workbook(db_session, user, _workbook(rows))

    assert len(outcomes) == 1
    assert outcomes[0].action == "flag"
    assert outcomes[0].category is None


def test_classify_marks_existing_source_as_update(db_session, user):
    db_session.add(
        Source(
            user_id=user.id,
            name="Acme Ventures",
            url="https://already-exists.example.com",
            category="vc_portfolio",
            adapter="auto",
        )
    )
    db_session.commit()

    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Acme Ventures", "https://already-exists.example.com"),
    ]
    outcomes = classify_workbook(db_session, user, _workbook(rows))

    assert [o.action for o in outcomes] == ["update"]


def test_commit_import_creates_sources_with_categories(db_session, user):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Acme Ventures", "https://commit-create.example.com"),
        ("JOBS NEWSLETTERS", None),
        ("NEWSLETTER", "URL"),
        ("Weekly Exec Jobs", "https://commit-create-newsletter.example.com"),
    ]
    commit_import(db_session, user, _workbook(rows), filename="test.xlsx")

    vc_source = db_session.scalar(
        select(Source).where(Source.url == "https://commit-create.example.com")
    )
    newsletter_source = db_session.scalar(
        select(Source).where(Source.url == "https://commit-create-newsletter.example.com")
    )
    assert vc_source is not None
    assert vc_source.category == "vc_portfolio"
    assert vc_source.enabled is True

    assert newsletter_source is not None
    assert newsletter_source.category == "newsletter"
    assert newsletter_source.enabled is False


def test_commit_import_twice_is_idempotent(db_session, user):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Acme Ventures", "https://idempotent.example.com"),
    ]

    first = commit_import(db_session, user, _workbook(rows), filename="test.xlsx")
    second = commit_import(db_session, user, _workbook(rows), filename="test.xlsx")

    assert (first.created_count, first.updated_count) == (1, 0)
    assert (second.created_count, second.updated_count) == (0, 1)

    matches = db_session.scalars(
        select(Source).where(Source.url == "https://idempotent.example.com")
    ).all()
    assert len(matches) == 1


def test_commit_import_does_not_reset_enabled_after_user_edit(db_session, user):
    rows = [
        ("JOBS NEWSLETTERS", None),
        ("NEWSLETTER", "URL"),
        ("Weekly Exec Jobs", "https://user-enabled-newsletter.example.com"),
    ]
    commit_import(db_session, user, _workbook(rows), filename="test.xlsx")

    source = db_session.scalar(
        select(Source).where(Source.url == "https://user-enabled-newsletter.example.com")
    )
    assert source.enabled is False
    source.enabled = True
    db_session.commit()

    commit_import(db_session, user, _workbook(rows), filename="test.xlsx")

    db_session.refresh(source)
    assert source.enabled is True


def test_commit_import_retains_a_report(db_session, user):
    rows = [
        ("VC FIRM", "JOB AGGREGATOR URL"),
        ("Acme Ventures", "https://report-test.example.com"),
        ("Mystery Co", "https://report-flagged.example.com"),
        ("Mystery Co", "https://report-flagged.example.com"),
    ]
    commit_import(db_session, user, _workbook(rows), filename="report-test.xlsx")

    run = db_session.scalar(
        select(SourceImportRun).where(SourceImportRun.user_id == user.id)
    )
    assert run is not None
    assert run.filename == "report-test.xlsx"
    assert run.created_count == 2
    assert run.updated_count == 0
    assert run.flagged_count == 1
    assert run.flagged_rows[0]["url"] == "https://report-flagged.example.com"
