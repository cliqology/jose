import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from jose.collectors.ashby import AshbyCollector
from jose.collectors.base import CollectorError
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


class SequentialFakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requested_urls: list[str] = []

    def __enter__(self) -> "SequentialFakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    @contextmanager
    def stream(self, method: str, url: str, **_: object) -> Iterator[FakeResponse]:
        self.requested_urls.append(url)
        yield self.responses.pop(0)


def patch_sequential_client(
    monkeypatch: pytest.MonkeyPatch, module_path: str, responses: list[FakeResponse]
) -> SequentialFakeClient:
    client = SequentialFakeClient(responses)
    monkeypatch.setattr(f"{module_path}.create_http_client", lambda: client)
    return client


def test_ashby_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.ashby",
        FakeResponse(payload=json_fixture("ashby.json")),
    )
    result = AshbyCollector().collect("Example", "https://jobs.ashbyhq.com/example")
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Chief Operating Officer"
    assert result.jobs[0].compensation_min == 225000
    assert result.jobs[0].published_at is not None
    assert result.rejected_count == 0


def test_greenhouse_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.greenhouse",
        FakeResponse(payload=json_fixture("greenhouse.json")),
    )
    result = GreenhouseCollector().collect("Example", "https://boards.greenhouse.io/example")
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "General Manager"
    assert result.jobs[0].description_text == "Own the business unit."
    assert result.jobs[0].external_job_id == "42"
    assert result.jobs[0].company_name == "Example Co"
    assert result.rejected_count == 0


def test_lever_collector_accepts_epoch_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.lever",
        FakeResponse(payload=json_fixture("lever.json")),
    )
    result = LeverCollector().collect("Example", "https://jobs.lever.co/example")
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "President"
    assert result.jobs[0].published_at is not None
    assert result.jobs[0].published_at.tzinfo is not None
    assert result.rejected_count == 0


def test_jsonld_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.jsonld",
        FakeResponse(text=(FIXTURES / "jobposting.html").read_text()),
    )
    result = JsonLdCollector().collect("Fallback Name", "https://example.com/careers")
    assert len(result.jobs) == 1
    assert result.jobs[0].company_name == "Example Labs"
    assert result.jobs[0].location == "New York, NY, US"
    assert result.jobs[0].employment_type == "FULL_TIME"
    assert result.rejected_count == 0


def test_jsonld_collector_matches_list_form_type(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.jsonld",
        FakeResponse(text=(FIXTURES / "jobposting_list_type.html").read_text()),
    )
    result = JsonLdCollector().collect("Fallback Name", "https://example.com/careers")
    assert len(result.jobs) == 1
    assert result.jobs[0].company_name == "Example Labs"
    assert result.jobs[0].location == "New York, NY, US"
    assert result.jobs[0].employment_type == "FULL_TIME"
    assert result.rejected_count == 0


def test_ashby_collector_returns_empty_for_no_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.ashby",
        FakeResponse(payload={"jobs": []}),
    )
    result = AshbyCollector().collect("Example", "https://jobs.ashbyhq.com/example")
    assert result.jobs == []
    assert result.rejected_count == 0


def test_ashby_collector_raises_on_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.ashby",
        FakeResponse(payload={"unexpected": "shape"}),
    )
    with pytest.raises(CollectorError):
        AshbyCollector().collect("Example", "https://jobs.ashbyhq.com/example")


def test_ashby_collector_rejects_job_missing_application_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json_fixture("ashby.json")
    payload["jobs"].append({"id": "ashby-2", "title": "No URL Role"})
    patch_client(monkeypatch, "jose.collectors.ashby", FakeResponse(payload=payload))

    result = AshbyCollector().collect("Example", "https://jobs.ashbyhq.com/example")

    assert len(result.jobs) == 1
    assert result.rejected_count == 1


def test_ashby_collector_treats_fractional_hourly_compensation_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json_fixture("ashby.json")
    payload["jobs"].append(
        {
            "id": "ashby-3",
            "title": "Contractor Role",
            "applyUrl": "https://jobs.ashbyhq.com/example/ashby-3/application",
            "compensation": {
                "summaryComponents": [
                    {
                        "compensationType": "Salary",
                        "interval": "1 HOUR",
                        "minValue": 60.58,
                        "maxValue": 108.17,
                        "currencyCode": "USD",
                    }
                ]
            },
        }
    )
    patch_client(monkeypatch, "jose.collectors.ashby", FakeResponse(payload=payload))

    result = AshbyCollector().collect("Example", "https://jobs.ashbyhq.com/example")

    assert result.rejected_count == 0
    contractor_role = next(job for job in result.jobs if job.title == "Contractor Role")
    assert contractor_role.compensation_min is None
    assert contractor_role.compensation_max is None


def test_greenhouse_collector_returns_empty_for_no_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.greenhouse",
        FakeResponse(payload={"jobs": []}),
    )
    result = GreenhouseCollector().collect("Example", "https://boards.greenhouse.io/example")
    assert result.jobs == []
    assert result.rejected_count == 0


def test_greenhouse_collector_raises_on_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.greenhouse",
        FakeResponse(payload={"unexpected": "shape"}),
    )
    with pytest.raises(CollectorError):
        GreenhouseCollector().collect("Example", "https://boards.greenhouse.io/example")


def test_greenhouse_collector_rejects_job_missing_application_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json_fixture("greenhouse.json")
    payload["jobs"].append({"id": 99, "title": "No URL Role"})
    patch_client(monkeypatch, "jose.collectors.greenhouse", FakeResponse(payload=payload))

    result = GreenhouseCollector().collect("Example", "https://boards.greenhouse.io/example")

    assert len(result.jobs) == 1
    assert result.rejected_count == 1


def test_lever_collector_returns_empty_for_no_postings(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(monkeypatch, "jose.collectors.lever", FakeResponse(payload=[]))
    result = LeverCollector().collect("Example", "https://jobs.lever.co/example")
    assert result.jobs == []
    assert result.rejected_count == 0


def test_lever_collector_raises_on_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_client(
        monkeypatch,
        "jose.collectors.lever",
        FakeResponse(payload={"ok": False, "error": "boom"}),
    )
    with pytest.raises(CollectorError):
        LeverCollector().collect("Example", "https://jobs.lever.co/example")


def test_lever_collector_rejects_job_missing_application_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json_fixture("lever.json")
    payload.append({"id": "lever-8", "text": "No URL Role", "categories": {}})
    patch_client(monkeypatch, "jose.collectors.lever", FakeResponse(payload=payload))

    result = LeverCollector().collect("Example", "https://jobs.lever.co/example")

    assert len(result.jobs) == 1
    assert result.rejected_count == 1


def test_lever_collector_parses_salary_range(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": "lever-9",
            "text": "VP Sales",
            "hostedUrl": "https://jobs.lever.co/example/lever-9",
            "categories": {},
            "createdAt": 1785157200000,
            "salaryRange": {
                "currency": "USD",
                "interval": "year",
                "min": 180000,
                "max": 220000,
            },
        }
    ]
    patch_client(monkeypatch, "jose.collectors.lever", FakeResponse(payload=payload))

    result = LeverCollector().collect("Example", "https://jobs.lever.co/example")

    assert len(result.jobs) == 1
    assert result.jobs[0].compensation_min == 180000
    assert result.jobs[0].compensation_max == 220000
    assert result.jobs[0].currency == "USD"


def test_lever_collector_paginates_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LeverCollector, "PAGE_SIZE", 2)
    page_1 = [
        {
            "id": "l-1",
            "text": "Role 1",
            "hostedUrl": "https://jobs.lever.co/example/l-1",
            "categories": {},
            "createdAt": 1785157200000,
        },
        {
            "id": "l-2",
            "text": "Role 2",
            "hostedUrl": "https://jobs.lever.co/example/l-2",
            "categories": {},
            "createdAt": 1785157200000,
        },
    ]
    page_2 = [
        {
            "id": "l-3",
            "text": "Role 3",
            "hostedUrl": "https://jobs.lever.co/example/l-3",
            "categories": {},
            "createdAt": 1785157200000,
        }
    ]
    client = patch_sequential_client(
        monkeypatch,
        "jose.collectors.lever",
        [FakeResponse(payload=page_1), FakeResponse(payload=page_2)],
    )

    result = LeverCollector().collect("Example", "https://jobs.lever.co/example")

    assert len(result.jobs) == 3
    assert len(client.requested_urls) == 2


def test_lever_collector_stops_at_max_pages_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(LeverCollector, "PAGE_SIZE", 2)
    monkeypatch.setattr(LeverCollector, "MAX_PAGES", 2)
    full_page = [
        {
            "id": "l-1",
            "text": "Role 1",
            "hostedUrl": "https://jobs.lever.co/example/l-1",
            "categories": {},
            "createdAt": 1785157200000,
        },
        {
            "id": "l-2",
            "text": "Role 2",
            "hostedUrl": "https://jobs.lever.co/example/l-2",
            "categories": {},
            "createdAt": 1785157200000,
        },
    ]
    patch_sequential_client(
        monkeypatch,
        "jose.collectors.lever",
        [FakeResponse(payload=full_page), FakeResponse(payload=full_page)],
    )
    caplog.set_level("WARNING", logger="jose.collectors.lever")

    result = LeverCollector().collect("Example", "https://jobs.lever.co/example")

    assert len(result.jobs) == 4
    assert "MAX_PAGES" in caplog.text
