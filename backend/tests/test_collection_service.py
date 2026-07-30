import pytest
from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.config import get_settings
from jose.models import Job, SourceRun
from jose.schemas import SourceCreate
from jose.services.collection import collect_source
from jose.services.sources import create_source


class _FakeCollector:
    def __init__(self, jobs: list[CollectedJob], rejected_count: int = 0) -> None:
        self._jobs = jobs
        self._rejected_count = rejected_count
        self.received_urls: list[str] = []

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        self.received_urls.append(source_url)
        return CollectionResult(jobs=self._jobs, rejected_count=self._rejected_count)


def test_collect_source_records_rejected_count(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme.example.com/jobs")
    )
    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://acme.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([job], rejected_count=3),
    )

    run = collect_source(db_session, source.id)

    assert run.status == "success"
    assert run.jobs_created == 1
    assert run.jobs_rejected == 3


def test_collect_source_clears_raw_payload_when_retention_disabled(db_session, user, monkeypatch):
    monkeypatch.setattr(get_settings(), "collector_retain_raw_payload", False)
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme2.example.com/jobs")
    )
    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://acme2.example.com/apply/1",
        raw_payload={"secret": "payload"},
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([job]),
    )

    collect_source(db_session, source.id)

    job_row = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert job_row is not None
    assert job_row.raw_payload == {}


def test_collect_source_uses_detected_application_url_when_supported(
    db_session, user, monkeypatch
):
    source = create_source(
        db_session,
        user,
        SourceCreate(name="Wrapper VC", url="https://jobs.wrappervc.com/portfolio"),
    )
    source.adapter = "greenhouse"
    source.detection_status = "supported"
    source.detected_application_url = "https://boards.greenhouse.io/wrappervc-portco"
    db_session.commit()

    job = CollectedJob(
        company_name="Portco",
        title="Engineer",
        application_url="https://boards.greenhouse.io/wrappervc-portco/jobs/1",
    )
    fake_collector = _FakeCollector([job])
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: fake_collector,
    )

    run = collect_source(db_session, source.id)

    assert run.status == "success"
    assert fake_collector.received_urls == ["https://boards.greenhouse.io/wrappervc-portco"]


def test_collect_source_falls_back_to_source_url_when_not_probed(db_session, user, monkeypatch):
    source = create_source(
        db_session,
        user,
        SourceCreate(name="Direct ATS", url="https://boards.greenhouse.io/direct"),
    )
    fake_collector = _FakeCollector([])
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: fake_collector,
    )

    collect_source(db_session, source.id)

    assert fake_collector.received_urls == ["https://boards.greenhouse.io/direct"]


def test_collect_source_retains_raw_payload_by_default(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme3.example.com/jobs")
    )
    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://acme3.example.com/apply/1",
        raw_payload={"secret": "payload"},
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([job]),
    )

    collect_source(db_session, source.id)

    job_row = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert job_row is not None
    assert job_row.raw_payload == {"secret": "payload"}


class _FailingCollector:
    def __init__(self, message: str) -> None:
        self._message = message

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        raise RuntimeError(self._message)


def test_collect_source_increments_consecutive_failures(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Flaky", url="https://flaky.example.com/jobs")
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector("boom"),
    )

    with pytest.raises(RuntimeError):
        collect_source(db_session, source.id)
    db_session.refresh(source)
    assert source.consecutive_failures == 1

    with pytest.raises(RuntimeError):
        collect_source(db_session, source.id)
    db_session.refresh(source)
    assert source.consecutive_failures == 2


def test_collect_source_resets_consecutive_failures_on_success(db_session, user, monkeypatch):
    source = create_source(
        db_session,
        user,
        SourceCreate(name="Recovering", url="https://recovering.example.com/jobs"),
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector("boom"),
    )
    with pytest.raises(RuntimeError):
        collect_source(db_session, source.id)
    db_session.refresh(source)
    assert source.consecutive_failures == 1

    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://recovering.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([job]),
    )
    collect_source(db_session, source.id)
    db_session.refresh(source)
    assert source.consecutive_failures == 0


def test_collect_source_sanitizes_error_message(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Leaky", url="https://leaky.example.com/jobs")
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector(
            "GET https://leaky.example.com/jobs?api_key=sk-live-abc123 -> 401"
        ),
    )

    with pytest.raises(RuntimeError):
        collect_source(db_session, source.id)

    db_session.refresh(source)
    run = db_session.scalar(
        select(SourceRun)
        .where(SourceRun.source_id == source.id)
        .order_by(SourceRun.started_at.desc())
    )
    assert run is not None
    assert "sk-live-abc123" not in source.last_error
    assert "sk-live-abc123" not in run.error_message
    assert "api_key=[redacted]" in source.last_error
