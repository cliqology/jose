import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from jose.collectors.ashby import AshbyCollector
from jose.collectors.greenhouse import GreenhouseCollector
from jose.collectors.jsonld import JsonLdCollector
from jose.collectors.lever import LeverCollector

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, *, payload: Any = None, text: str = "", status_code: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8") if payload is not None else text.encode(
            "utf-8"
        )
        self.status_code = status_code
        self.headers = httpx.Headers({})
        self.request = httpx.Request("GET", "https://example.com/")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return json.loads(self._body)

    @property
    def text(self) -> str:
        return self._body.decode("utf-8")

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._body


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requested_url: str | None = None

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get(self, url: str, **_: object) -> FakeResponse:
        self.requested_url = url
        return self.response

    @contextmanager
    def stream(self, method: str, url: str, **_: object) -> Iterator[FakeResponse]:
        self.requested_url = url
        yield self.response


def json_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def patch_client(monkeypatch: pytest.MonkeyPatch, module_path: str, response: FakeResponse) -> None:
    client = FakeClient(response)
    monkeypatch.setattr(f"{module_path}.create_http_client", lambda: client)


def test_ashby_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.ashby",
        FakeResponse(payload=json_fixture("ashby.json")),
    )
    jobs = AshbyCollector().collect("Example", "https://jobs.ashbyhq.com/example")
    assert len(jobs) == 1
    assert jobs[0].title == "Chief Operating Officer"
    assert jobs[0].compensation_min == 225000
    assert jobs[0].published_at is not None


def test_greenhouse_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.greenhouse",
        FakeResponse(payload=json_fixture("greenhouse.json")),
    )
    jobs = GreenhouseCollector().collect("Example", "https://boards.greenhouse.io/example")
    assert len(jobs) == 1
    assert jobs[0].title == "General Manager"
    assert jobs[0].description_text == "Own the business unit."
    assert jobs[0].external_job_id == "42"


def test_lever_collector_accepts_epoch_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.lever",
        FakeResponse(payload=json_fixture("lever.json")),
    )
    jobs = LeverCollector().collect("Example", "https://jobs.lever.co/example")
    assert len(jobs) == 1
    assert jobs[0].title == "President"
    assert jobs[0].published_at is not None
    assert jobs[0].published_at.tzinfo is not None


def test_jsonld_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.jsonld",
        FakeResponse(text=(FIXTURES / "jobposting.html").read_text()),
    )
    jobs = JsonLdCollector().collect("Fallback Name", "https://example.com/careers")
    assert len(jobs) == 1
    assert jobs[0].company_name == "Example Labs"
    assert jobs[0].location == "New York, NY, US"
    assert jobs[0].employment_type == "FULL_TIME"
