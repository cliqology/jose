from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from jose.services.platform_detection import AGGREGATOR_SIGNATURES, probe_source


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
