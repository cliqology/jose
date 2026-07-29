from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from jose.schemas import SourceCategory, SourceCreate
from jose.services.platform_detection import (
    AGGREGATOR_SIGNATURES,
    ProbeOutcome,
    detect_platforms_for_vc_sources,
    probe_source,
    render_source_catalog,
)
from jose.services.sources import create_source


class FakeResponse:
    def __init__(
        self, *, text: str = "", status_code: int = 200, final_url: str = "https://example.com/"
    ) -> None:
        self._body = text.encode("utf-8")
        self.status_code = status_code
        self.headers = httpx.Headers({})
        self.request = httpx.Request("GET", final_url)

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._body


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    @contextmanager
    def stream(self, method: str, url: str, **_: object) -> Iterator[FakeResponse]:
        yield self.response


def patch_client(monkeypatch: pytest.MonkeyPatch, response: FakeResponse) -> None:
    monkeypatch.setattr(
        "jose.services.platform_detection.create_http_client", lambda: FakeClient(response)
    )


def test_probe_source_matches_known_ats_host(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch, FakeResponse(final_url="https://boards.greenhouse.io/examplevc-portco")
    )

    outcome = probe_source("https://jobs.examplevc.com/")

    assert outcome.status == "supported"
    assert outcome.adapter == "greenhouse"
    assert outcome.detected_platform == "greenhouse"
    assert outcome.detected_application_url == "https://boards.greenhouse.io/examplevc-portco"
    assert outcome.error is None


def test_probe_source_detects_json_ld_job_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        '<html><body><script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Engineer"}'
        "</script></body></html>"
    )
    patch_client(monkeypatch, FakeResponse(text=html, final_url="https://jobs.examplevc.com/"))

    outcome = probe_source("https://jobs.examplevc.com/")

    assert outcome.status == "supported"
    assert outcome.adapter == "jsonld"
    assert outcome.detected_platform == "jsonld"


def test_probe_source_matches_aggregator_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    needle, platform = next(iter(AGGREGATOR_SIGNATURES.items()))
    patch_client(monkeypatch, FakeResponse(final_url=f"https://jobs.examplevc.{needle}"))

    outcome = probe_source("https://jobs.examplevc.com/")

    assert outcome.status == "unsupported"
    assert outcome.detected_platform == platform
    assert outcome.adapter == "unsupported"


def test_probe_source_uncertain_when_nothing_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        FakeResponse(
            text="<html><body>No structured data here.</body></html>",
            final_url="https://jobs.examplevc.com/",
        ),
    )

    outcome = probe_source("https://jobs.examplevc.com/")

    assert outcome.status == "uncertain"
    assert outcome.detected_platform is None
    assert outcome.adapter == "unsupported"


def test_probe_source_records_error_on_failed_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(monkeypatch, FakeResponse(status_code=500))

    outcome = probe_source("https://jobs.examplevc.com/")

    assert outcome.status == "error"
    assert outcome.adapter is None
    assert outcome.detected_platform is None
    assert outcome.error is not None


def test_detect_platforms_only_probes_vc_sources(db_session, user, monkeypatch):
    vc_one = create_source(
        db_session,
        user,
        SourceCreate(
            name="VC One", url="https://jobs.vcone.com/", category=SourceCategory.VC_PORTFOLIO
        ),
    )
    vc_two = create_source(
        db_session,
        user,
        SourceCreate(
            name="VC Two", url="https://jobs.vctwo.com/", category=SourceCategory.VC_PORTFOLIO
        ),
    )
    non_vc = create_source(
        db_session, user, SourceCreate(name="Direct ATS", url="https://boards.greenhouse.io/x")
    )

    def fake_probe(url: str) -> ProbeOutcome:
        return ProbeOutcome(
            status="uncertain",
            adapter="unsupported",
            detected_platform=None,
            detected_application_url=url,
            error=None,
        )

    monkeypatch.setattr("jose.services.platform_detection.probe_source", fake_probe)

    results = detect_platforms_for_vc_sources(db_session, user)

    probed_ids = {result.source_id for result in results}
    assert probed_ids == {vc_one.id, vc_two.id}

    db_session.refresh(non_vc)
    assert non_vc.adapter == "auto"
    assert non_vc.detection_status is None

    db_session.refresh(vc_one)
    assert vc_one.adapter == "unsupported"
    assert vc_one.detection_status == "uncertain"
    assert vc_one.detected_at is not None


def test_detect_platforms_is_scoped_to_user(db_session, user, other_user, monkeypatch):
    mine = create_source(
        db_session,
        user,
        SourceCreate(
            name="Mine", url="https://jobs.mine.com/", category=SourceCategory.VC_PORTFOLIO
        ),
    )
    theirs = create_source(
        db_session,
        other_user,
        SourceCreate(
            name="Theirs", url="https://jobs.theirs.com/", category=SourceCategory.VC_PORTFOLIO
        ),
    )

    def fake_probe(url: str) -> ProbeOutcome:
        return ProbeOutcome(
            status="uncertain",
            adapter="unsupported",
            detected_platform=None,
            detected_application_url=url,
            error=None,
        )

    monkeypatch.setattr("jose.services.platform_detection.probe_source", fake_probe)

    results = detect_platforms_for_vc_sources(db_session, user)

    assert {result.source_id for result in results} == {mine.id}
    db_session.refresh(theirs)
    assert theirs.detection_status is None


def test_detect_platforms_records_error_without_overwriting_adapter(
    db_session, user, monkeypatch
):
    source = create_source(
        db_session,
        user,
        SourceCreate(
            name="Flaky", url="https://jobs.flaky.com/", category=SourceCategory.VC_PORTFOLIO
        ),
    )

    def fake_probe(url: str) -> ProbeOutcome:
        return ProbeOutcome(
            status="error",
            adapter=None,
            detected_platform=None,
            detected_application_url=None,
            error="Rate limited by https://jobs.flaky.com/",
        )

    monkeypatch.setattr("jose.services.platform_detection.probe_source", fake_probe)

    results = detect_platforms_for_vc_sources(db_session, user)

    assert results[0].status == "error"
    db_session.refresh(source)
    assert source.adapter == "auto"
    assert source.detection_status == "error"
    assert source.last_error == "Rate limited by https://jobs.flaky.com/"


def test_render_source_catalog_includes_vc_sources(db_session, user):
    source = create_source(
        db_session,
        user,
        SourceCreate(
            name="Example VC",
            url="https://jobs.examplevc.com/",
            category=SourceCategory.VC_PORTFOLIO,
        ),
    )
    source.detection_status = "supported"
    source.adapter = "jsonld"
    source.detected_platform = "jsonld"
    source.detected_application_url = "https://jobs.examplevc.com/board"
    db_session.commit()

    text = render_source_catalog(db_session, user)

    assert "Example VC" in text
    assert "https://jobs.examplevc.com/" in text
    assert "jsonld" in text
    assert "supported" in text
    assert "https://jobs.examplevc.com/board" in text
    assert "## Notes" in text


def test_render_source_catalog_handles_unprobed_source(db_session, user):
    create_source(
        db_session,
        user,
        SourceCreate(
            name="Not Yet Probed",
            url="https://jobs.notprobed.com/",
            category=SourceCategory.VC_PORTFOLIO,
        ),
    )

    text = render_source_catalog(db_session, user)

    assert "Not Yet Probed" in text
    assert "not probed" in text
