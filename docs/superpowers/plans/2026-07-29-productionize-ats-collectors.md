# Productionize ATS Collectors (Issue 04) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Ashby, Greenhouse, and Lever collectors production-ready per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 04 and `docs/superpowers/specs/2026-07-29-productionize-ats-collectors-design.md`.

**Architecture:** `Collector.collect()` moves from returning a bare `list[CollectedJob]` to a `CollectionResult` (jobs + rejected_count), giving each adapter a channel to report dropped items without failing the whole run. Each ATS adapter validates its top-level response shape (raising `CollectorError` on anything unexpected, per CLAUDE.md rule #5) before iterating, skips individual jobs missing an application URL, and gets an adapter-specific improvement: Greenhouse prefers the payload's real `company_name`, Lever paginates via `skip`/`limit` and parses its structured `salaryRange`. A new `SourceRun.jobs_rejected` column and `Settings.collector_retain_raw_payload` flag surface the new behavior.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, httpx, pytest. All backend commands run via `docker compose run --rm api ...` (Colima-backed Docker).

## Global Constraints

- Never invent career facts, dates, metrics, titles, employers, compensation, or personal information — unknown stays unknown (CLAUDE.md rule #3/#4). Applies directly to compensation parsing: only use fields the payload actually provides.
- A failed collector is a failure, never a successful zero-result run (CLAUDE.md rule #5). Malformed top-level responses must raise `CollectorError`, not silently return an empty list.
- No live network calls in unit tests — all collector tests use fixtures/fakes (CLAUDE.md working rule).
- Every user-owned record includes `user_id`; use timezone-aware UTC datetimes; use UUID primary keys (CLAUDE.md architecture rules) — already satisfied by existing models, no new violations to introduce.
- Add a migration whenever the persisted schema changes (CLAUDE.md working rule).
- Ruff must pass (line length 100, rules E/F/I/B/UP/SIM per `backend/pyproject.toml`).
- Definition of done: acceptance criteria met, unit tests pass, ruff passes, migrations included, error paths handled.

---

## Task 1: Migrate the Collector contract to `CollectionResult`

**Files:**
- Modify: `backend/jose/collectors/base.py`
- Modify: `backend/jose/collectors/__init__.py`
- Modify: `backend/jose/collectors/ashby.py`
- Modify: `backend/jose/collectors/greenhouse.py`
- Modify: `backend/jose/collectors/lever.py`
- Modify: `backend/jose/collectors/jsonld.py`
- Modify: `backend/jose/services/collection.py`
- Test: `backend/tests/test_collected_job.py`
- Test: `backend/tests/test_collectors_http.py`

**Interfaces:**
- Produces: `jose.collectors.base.CollectionResult` — `CollectionResult(jobs: list[CollectedJob], rejected_count: int = 0)`, frozen Pydantic model.
- Produces: `Collector.collect(source_name: str, source_url: str) -> CollectionResult` (was `-> list[CollectedJob]`) — the contract every later task builds on.
- Consumes: nothing from earlier tasks (this is the first task).

This task is a pure mechanical migration — every collector's *behavior* is identical to today, just wrapped in `CollectionResult(jobs=jobs)` with `rejected_count` always `0`. Adapter-specific hardening (malformed-response checks, rejected-job handling, company identification, pagination, compensation parsing) happens in Tasks 2–4. Keeping this migration isolated means the repo is fully working and tested after every commit — no task leaves `collection.py` calling collectors with a contract they no longer satisfy.

- [ ] **Step 1: Write the failing tests for `CollectionResult`**

Open `backend/tests/test_collected_job.py` and replace its import line and append two new tests, so the full file reads:

```python
import pytest
from pydantic import ValidationError

from jose.collectors.base import CollectedJob, CollectionResult


def test_collected_job_rejects_bad_field_type() -> None:
    with pytest.raises(ValidationError):
        CollectedJob(
            company_name="Acme",
            title="Engineer",
            application_url="https://acme.example/jobs/1",
            compensation_min={"not": "a number"},
        )


def test_collected_job_leaves_omitted_optional_fields_none() -> None:
    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://acme.example/jobs/1",
    )
    assert job.location is None
    assert job.compensation_min is None
    assert job.raw_payload == {}


def test_collected_job_ignores_unknown_fields() -> None:
    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://acme.example/jobs/1",
        totally_unexpected_field="surprise",
    )
    assert not hasattr(job, "totally_unexpected_field")


def test_collected_job_is_frozen() -> None:
    job = CollectedJob(
        company_name="Acme", title="Engineer", application_url="https://acme.example/jobs/1"
    )
    with pytest.raises(ValidationError):
        job.title = "Changed"


def test_collection_result_defaults_rejected_count_to_zero() -> None:
    job = CollectedJob(
        company_name="Acme", title="Engineer", application_url="https://acme.example/jobs/1"
    )
    result = CollectionResult(jobs=[job])
    assert result.jobs == [job]
    assert result.rejected_count == 0


def test_collection_result_is_frozen() -> None:
    result = CollectionResult(jobs=[])
    with pytest.raises(ValidationError):
        result.rejected_count = 5
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collected_job.py -v`
Expected: FAIL — `ImportError: cannot import name 'CollectionResult' from 'jose.collectors.base'`

- [ ] **Step 3: Add `CollectionResult` and update the `Collector` protocol in `base.py`**

Replace the full contents of `backend/jose/collectors/base.py` with:

```python
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class CollectedJob(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    company_name: str
    title: str
    application_url: str
    source_job_url: str | None = None
    description_text: str | None = None
    description_html: str | None = None
    department: str | None = None
    location: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    compensation_min: int | None = None
    compensation_max: int | None = None
    currency: str | None = None
    ats_type: str | None = None
    external_job_id: str | None = None
    published_at: datetime | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class CollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    jobs: list[CollectedJob]
    rejected_count: int = 0


class CollectorError(RuntimeError):
    pass


class UnsupportedSourceError(CollectorError):
    pass


class RateLimitError(CollectorError):
    pass


class AccessDeniedError(CollectorError):
    pass


class UnsafeURLError(CollectorError):
    pass


class Collector(Protocol):
    name: str

    def collect(self, source_name: str, source_url: str) -> CollectionResult: ...
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collected_job.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Export `CollectionResult` from the collectors package**

Replace the full contents of `backend/jose/collectors/__init__.py` with:

```python
from jose.collectors.base import (
    CollectedJob,
    CollectionResult,
    CollectorError,
    UnsupportedSourceError,
)
from jose.collectors.registry import detect_adapter, get_collector

__all__ = [
    "CollectedJob",
    "CollectionResult",
    "CollectorError",
    "UnsupportedSourceError",
    "detect_adapter",
    "get_collector",
]
```

- [ ] **Step 6: Wrap Ashby's return value**

Replace the full contents of `backend/jose/collectors/ashby.py` with:

```python
from urllib.parse import urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class AshbyCollector:
    name = "ashby"

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        board_name = urlsplit(source_url).path.strip("/").split("/")[0]
        if not board_name:
            raise CollectorError("Unable to determine Ashby job-board name")

        endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"includeCompensation": "true"})
            data = response.json()

        jobs: list[CollectedJob] = []
        for item in data.get("jobs", []):
            compensation = item.get("compensation") or {}
            salary_components = [
                component
                for component in compensation.get("summaryComponents", [])
                if component.get("compensationType") == "Salary"
            ]
            salary = salary_components[0] if salary_components else {}
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=item.get("applyUrl") or item.get("jobUrl"),
                    source_job_url=item.get("jobUrl"),
                    description_text=item.get("descriptionPlain")
                    or html_to_text(item.get("descriptionHtml")),
                    description_html=item.get("descriptionHtml"),
                    department=item.get("department") or item.get("team"),
                    location=item.get("location"),
                    remote_type=item.get("workplaceType")
                    or ("Remote" if item.get("isRemote") else None),
                    employment_type=item.get("employmentType"),
                    compensation_min=salary.get("minValue"),
                    compensation_max=salary.get("maxValue"),
                    currency=salary.get("currencyCode"),
                    ats_type="ashby",
                    external_job_id=item.get("id") or item.get("jobUrl"),
                    published_at=parse_datetime(item.get("publishedAt")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs)
```

- [ ] **Step 7: Wrap Greenhouse's return value**

Replace the full contents of `backend/jose/collectors/greenhouse.py` with:

```python
from urllib.parse import parse_qs, urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class GreenhouseCollector:
    name = "greenhouse"

    @staticmethod
    def _board_token(source_url: str) -> str:
        parts = urlsplit(source_url)
        path_parts = [part for part in parts.path.split("/") if part]
        if parts.netloc in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and path_parts:
            return path_parts[0]
        query = parse_qs(parts.query)
        if "for" in query and query["for"]:
            return query["for"][0]
        raise CollectorError("Unable to determine Greenhouse board token")

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        token = self._board_token(source_url)
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"content": "true"})
            data = response.json()

        jobs: list[CollectedJob] = []
        for item in data.get("jobs", []):
            departments = item.get("departments") or []
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=item.get("absolute_url"),
                    source_job_url=item.get("absolute_url"),
                    description_text=html_to_text(item.get("content")),
                    description_html=item.get("content"),
                    department=departments[0].get("name") if departments else None,
                    location=(item.get("location") or {}).get("name"),
                    ats_type="greenhouse",
                    external_job_id=str(item.get("id")) if item.get("id") is not None else None,
                    published_at=parse_datetime(item.get("first_published")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs)
```

- [ ] **Step 8: Wrap Lever's return value**

Replace the full contents of `backend/jose/collectors/lever.py` with:

```python
from urllib.parse import urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class LeverCollector:
    name = "lever"

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        parts = [part for part in urlsplit(source_url).path.split("/") if part]
        if not parts:
            raise CollectorError("Unable to determine Lever site name")
        site = parts[0]
        endpoint = f"https://api.lever.co/v0/postings/{site}"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"mode": "json"})
            data = response.json()

        jobs: list[CollectedJob] = []
        for item in data:
            categories = item.get("categories") or {}
            description_html = item.get("description") or item.get("descriptionBody")
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("text") or "Untitled role",
                    application_url=item.get("applyUrl") or item.get("hostedUrl"),
                    source_job_url=item.get("hostedUrl"),
                    description_text=html_to_text(description_html),
                    description_html=description_html,
                    department=categories.get("department") or categories.get("team"),
                    location=categories.get("location"),
                    remote_type=categories.get("commitment"),
                    employment_type=categories.get("commitment"),
                    ats_type="lever",
                    external_job_id=item.get("id"),
                    published_at=parse_datetime(item.get("createdAt")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs)
```

- [ ] **Step 9: Wrap JsonLd's return value**

Replace the full contents of `backend/jose/collectors/jsonld.py` with:

```python
import json
from collections.abc import Iterable
from typing import Any

from bs4 import BeautifulSoup

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class JsonLdCollector:
    name = "jsonld"

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        with create_http_client() as client:
            response = safe_get(client, source_url)

        soup = BeautifulSoup(response.text, "html.parser")
        postings: list[dict[str, Any]] = []
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                parsed = json.loads(tag.string or tag.get_text())
            except json.JSONDecodeError:
                continue
            postings.extend(self._find_postings(parsed))

        if not postings:
            raise CollectorError("No JSON-LD JobPosting records found")

        jobs: list[CollectedJob] = []
        for item in postings:
            organization = item.get("hiringOrganization") or {}
            location = self._location(item.get("jobLocation"))
            jobs.append(
                CollectedJob(
                    company_name=organization.get("name") or source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=item.get("url") or source_url,
                    source_job_url=item.get("url") or source_url,
                    description_text=html_to_text(item.get("description")),
                    description_html=item.get("description"),
                    location=location,
                    remote_type=item.get("jobLocationType"),
                    employment_type=self._first(item.get("employmentType")),
                    ats_type="jsonld",
                    external_job_id=str(item.get("identifier") or item.get("url") or ""),
                    published_at=parse_datetime(item.get("datePosted")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs)

    def _find_postings(self, value: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if value.get("@type") == "JobPosting":
                results.append(value)
            graph = value.get("@graph")
            if graph:
                results.extend(self._find_postings(graph))
            for key, child in value.items():
                if key != "@graph" and isinstance(child, (dict, list)):
                    results.extend(self._find_postings(child))
        elif isinstance(value, list):
            for child in value:
                results.extend(self._find_postings(child))
        return results

    @staticmethod
    def _location(value: Any) -> str | None:
        entries: Iterable[Any] = value if isinstance(value, list) else [value]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            address = entry.get("address") or {}
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            result = ", ".join(str(part) for part in parts if part)
            if result:
                return result
        return None

    @staticmethod
    def _first(value: Any) -> str | None:
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value) if value else None
```

- [ ] **Step 10: Update `collection.py` to read `result.jobs`**

In `backend/jose/services/collection.py`, replace the `try:` block inside `collect_source` — from `try:` through `return run` (just before `except Exception as exc:`) — with:

```python
    try:
        collector = get_collector(source.url, source.adapter)
        result = collector.collect(source.name, source.url)
        created = 0
        updated = 0
        for item in result.jobs:
            was_created, was_updated = _upsert_job(session, source, item)
            created += int(was_created)
            updated += int(was_updated)

        run = session.get(SourceRun, run.id)
        source = session.get(Source, source.id)
        assert run is not None and source is not None
        run.status = "success"
        run.completed_at = utcnow()
        run.jobs_found = len(result.jobs)
        run.jobs_created = created
        run.jobs_updated = updated
        source.last_success_at = utcnow()
        source.last_job_count = len(result.jobs)
        source.last_error = None
        session.commit()
        return run
```

(`run.jobs_rejected` is deliberately not set here — that column doesn't exist yet and is wired up in Task 5.)

- [ ] **Step 11: Update the collector test fixtures file to use `.jobs`**

Replace the full contents of `backend/tests/test_collectors_http.py` with:

```python
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
```

- [ ] **Step 12: Run the full test suite to verify everything still passes**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest -q"`
Expected: PASS, all existing tests green (nothing else in the codebase called `collect()` directly, so this is the full blast radius of the contract change).

- [ ] **Step 13: Commit**

```bash
git add backend/jose/collectors/base.py backend/jose/collectors/__init__.py \
  backend/jose/collectors/ashby.py backend/jose/collectors/greenhouse.py \
  backend/jose/collectors/lever.py backend/jose/collectors/jsonld.py \
  backend/jose/services/collection.py backend/tests/test_collected_job.py \
  backend/tests/test_collectors_http.py
git commit -m "refactor: migrate Collector.collect() to return CollectionResult"
```

---

## Task 2: Harden the Ashby collector

**Files:**
- Modify: `backend/jose/collectors/ashby.py`
- Modify: `backend/tests/test_collectors_http.py`

**Interfaces:**
- Consumes: `CollectionResult`, `CollectedJob`, `CollectorError` from `jose.collectors.base` (Task 1).
- Produces: no new public interface — `AshbyCollector.collect()` now raises `CollectorError` on a malformed top-level shape and returns a non-zero `rejected_count` when jobs are skipped, per the `Collector` protocol already defined.

- [ ] **Step 1: Write the failing tests**

Add the import for `CollectorError` — replace:

```python
from jose.collectors.ashby import AshbyCollector
from jose.collectors.greenhouse import GreenhouseCollector
```

with:

```python
from jose.collectors.ashby import AshbyCollector
from jose.collectors.base import CollectorError
from jose.collectors.greenhouse import GreenhouseCollector
```

Then append these three tests to the end of `backend/tests/test_collectors_http.py` (after `test_jsonld_collector`):

```python


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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -k ashby -v`
Expected: FAIL — `test_ashby_collector_returns_empty_for_no_jobs` passes already (matches current behavior), but `test_ashby_collector_raises_on_malformed_response` fails (no error raised — `data.get("jobs", [])` silently returns `[]`), and `test_ashby_collector_rejects_job_missing_application_url` fails with a Pydantic `ValidationError` instead of skipping the bad entry.

- [ ] **Step 3: Implement the hardening**

Replace the full contents of `backend/jose/collectors/ashby.py` with:

```python
import logging
from urllib.parse import urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime

logger = logging.getLogger(__name__)


class AshbyCollector:
    name = "ashby"

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        board_name = urlsplit(source_url).path.strip("/").split("/")[0]
        if not board_name:
            raise CollectorError("Unable to determine Ashby job-board name")

        endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"includeCompensation": "true"})
            data = response.json()

        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise CollectorError(f"Unexpected Ashby response shape from {endpoint}")

        jobs: list[CollectedJob] = []
        rejected_count = 0
        for item in data["jobs"]:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict Ashby job entry: %r", item)
                rejected_count += 1
                continue

            application_url = item.get("applyUrl") or item.get("jobUrl")
            if not application_url:
                logger.warning(
                    "Skipping Ashby job missing application URL: id=%s title=%s",
                    item.get("id"),
                    item.get("title"),
                )
                rejected_count += 1
                continue

            compensation = item.get("compensation") or {}
            salary_components = [
                component
                for component in compensation.get("summaryComponents", [])
                if component.get("compensationType") == "Salary"
            ]
            salary = salary_components[0] if salary_components else {}
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=application_url,
                    source_job_url=item.get("jobUrl"),
                    description_text=item.get("descriptionPlain")
                    or html_to_text(item.get("descriptionHtml")),
                    description_html=item.get("descriptionHtml"),
                    department=item.get("department") or item.get("team"),
                    location=item.get("location"),
                    remote_type=item.get("workplaceType")
                    or ("Remote" if item.get("isRemote") else None),
                    employment_type=item.get("employmentType"),
                    compensation_min=salary.get("minValue"),
                    compensation_max=salary.get("maxValue"),
                    currency=salary.get("currencyCode"),
                    ats_type="ashby",
                    external_job_id=item.get("id") or item.get("jobUrl"),
                    published_at=parse_datetime(item.get("publishedAt")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs, rejected_count=rejected_count)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -k ashby -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `docker compose run --rm api pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/jose/collectors/ashby.py backend/tests/test_collectors_http.py
git commit -m "feat: harden Ashby collector against malformed responses and missing URLs"
```

---

## Task 3: Harden the Greenhouse collector and prefer its `company_name` field

**Files:**
- Modify: `backend/jose/collectors/greenhouse.py`
- Modify: `backend/tests/fixtures/greenhouse.json`
- Modify: `backend/tests/test_collectors_http.py`

**Interfaces:**
- Consumes: `CollectionResult`, `CollectedJob`, `CollectorError` from `jose.collectors.base` (Task 1).
- Produces: no new public interface — same shape as Task 2's Ashby hardening, plus `company_name` now sourced from the payload when Greenhouse provides it.

- [ ] **Step 1: Add `company_name` to the Greenhouse fixture**

Replace the full contents of `backend/tests/fixtures/greenhouse.json` with:

```json
{
  "jobs": [
    {
      "id": 42,
      "title": "General Manager",
      "company_name": "Example Co",
      "absolute_url": "https://boards.greenhouse.io/example/jobs/42",
      "content": "<p>Own the business unit.</p>",
      "departments": [{"name": "Executive"}],
      "location": {"name": "Remote, US"},
      "first_published": "2026-07-26T09:30:00-04:00"
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

In `backend/tests/test_collectors_http.py`, add a `company_name` assertion to `test_greenhouse_collector` — replace:

```python
    result = GreenhouseCollector().collect("Example", "https://boards.greenhouse.io/example")
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "General Manager"
    assert result.jobs[0].description_text == "Own the business unit."
    assert result.jobs[0].external_job_id == "42"
    assert result.rejected_count == 0
```

with:

```python
    result = GreenhouseCollector().collect("Example", "https://boards.greenhouse.io/example")
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "General Manager"
    assert result.jobs[0].description_text == "Own the business unit."
    assert result.jobs[0].external_job_id == "42"
    assert result.jobs[0].company_name == "Example Co"
    assert result.rejected_count == 0
```

Then append these three tests to the end of the file (after the Ashby edge-case tests added in Task 2):

```python


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
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -k greenhouse -v`
Expected: FAIL — `company_name` assertion fails (still `"Example"`, the source label), malformed-response test fails (no error raised), rejected-job test fails with a `ValidationError`.

- [ ] **Step 4: Implement the hardening**

Replace the full contents of `backend/jose/collectors/greenhouse.py` with:

```python
import logging
from urllib.parse import parse_qs, urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime

logger = logging.getLogger(__name__)


class GreenhouseCollector:
    name = "greenhouse"

    @staticmethod
    def _board_token(source_url: str) -> str:
        parts = urlsplit(source_url)
        path_parts = [part for part in parts.path.split("/") if part]
        if parts.netloc in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and path_parts:
            return path_parts[0]
        query = parse_qs(parts.query)
        if "for" in query and query["for"]:
            return query["for"][0]
        raise CollectorError("Unable to determine Greenhouse board token")

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        token = self._board_token(source_url)
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"content": "true"})
            data = response.json()

        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise CollectorError(f"Unexpected Greenhouse response shape from {endpoint}")

        jobs: list[CollectedJob] = []
        rejected_count = 0
        for item in data["jobs"]:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict Greenhouse job entry: %r", item)
                rejected_count += 1
                continue

            application_url = item.get("absolute_url")
            if not application_url:
                logger.warning(
                    "Skipping Greenhouse job missing application URL: id=%s title=%s",
                    item.get("id"),
                    item.get("title"),
                )
                rejected_count += 1
                continue

            departments = item.get("departments") or []
            jobs.append(
                CollectedJob(
                    company_name=item.get("company_name") or source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=application_url,
                    source_job_url=application_url,
                    description_text=html_to_text(item.get("content")),
                    description_html=item.get("content"),
                    department=departments[0].get("name") if departments else None,
                    location=(item.get("location") or {}).get("name"),
                    ats_type="greenhouse",
                    external_job_id=str(item.get("id")) if item.get("id") is not None else None,
                    published_at=parse_datetime(item.get("first_published")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs, rejected_count=rejected_count)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -k greenhouse -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `docker compose run --rm api pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/jose/collectors/greenhouse.py backend/tests/fixtures/greenhouse.json \
  backend/tests/test_collectors_http.py
git commit -m "feat: harden Greenhouse collector and prefer its company_name field"
```

---

## Task 4: Harden the Lever collector — pagination and compensation parsing

**Files:**
- Modify: `backend/jose/collectors/lever.py`
- Modify: `backend/tests/test_collectors_http.py`

**Interfaces:**
- Consumes: `CollectionResult`, `CollectedJob`, `CollectorError` from `jose.collectors.base` (Task 1).
- Produces: `LeverCollector.PAGE_SIZE` (class attribute, default `100`) and `LeverCollector.MAX_PAGES` (class attribute, default `50`) — tests monkeypatch these to exercise pagination and the page cap cheaply. `LeverCollector._fetch_all_pages(self, client: httpx.Client, endpoint: str) -> list[dict[str, Any]]` is a new internal helper.

Lever's public postings API genuinely supports `skip`/`limit` pagination (confirmed live — `limit=5&skip=100` returns the next slice) and a structured `salaryRange: {currency, interval, min, max}` field the current collector ignores. Ashby and Greenhouse don't paginate and expose no such field, so they don't get equivalent changes here.

- [ ] **Step 1: Write the failing tests**

Add a `SequentialFakeClient` test double (for multi-page responses) right after the existing `patch_client` helper in `backend/tests/test_collectors_http.py` — replace:

```python
def patch_client(monkeypatch: pytest.MonkeyPatch, module_path: str, response: FakeResponse) -> None:
    client = FakeClient(response)
    monkeypatch.setattr(f"{module_path}.create_http_client", lambda: client)
```

with:

```python
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
```

Then append these six tests to the end of the file (after the Greenhouse edge-case tests added in Task 3):

```python


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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -k lever -v`
Expected: FAIL — pagination tests fail (`FakeClient`/current collector only ever makes one request and ignores `PAGE_SIZE`/`MAX_PAGES`, which don't exist yet), salary test fails (`compensation_min` is `None`), malformed/rejected tests fail the same way as Ashby/Greenhouse did before hardening.

- [ ] **Step 3: Implement the hardening**

Replace the full contents of `backend/jose/collectors/lever.py` with:

```python
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime

logger = logging.getLogger(__name__)


class LeverCollector:
    name = "lever"
    PAGE_SIZE = 100
    MAX_PAGES = 50

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        parts = [part for part in urlsplit(source_url).path.split("/") if part]
        if not parts:
            raise CollectorError("Unable to determine Lever site name")
        site = parts[0]
        endpoint = f"https://api.lever.co/v0/postings/{site}"
        with create_http_client() as client:
            items = self._fetch_all_pages(client, endpoint)

        jobs: list[CollectedJob] = []
        rejected_count = 0
        for item in items:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict Lever job entry: %r", item)
                rejected_count += 1
                continue

            application_url = item.get("applyUrl") or item.get("hostedUrl")
            if not application_url:
                logger.warning(
                    "Skipping Lever job missing application URL: id=%s title=%s",
                    item.get("id"),
                    item.get("text"),
                )
                rejected_count += 1
                continue

            categories = item.get("categories") or {}
            salary_range = item.get("salaryRange") or {}
            description_html = item.get("description") or item.get("descriptionBody")
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("text") or "Untitled role",
                    application_url=application_url,
                    source_job_url=item.get("hostedUrl"),
                    description_text=html_to_text(description_html),
                    description_html=description_html,
                    department=categories.get("department") or categories.get("team"),
                    location=categories.get("location"),
                    remote_type=categories.get("commitment"),
                    employment_type=categories.get("commitment"),
                    compensation_min=salary_range.get("min"),
                    compensation_max=salary_range.get("max"),
                    currency=salary_range.get("currency"),
                    ats_type="lever",
                    external_job_id=item.get("id"),
                    published_at=parse_datetime(item.get("createdAt")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs, rejected_count=rejected_count)

    def _fetch_all_pages(self, client: httpx.Client, endpoint: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        skip = 0
        for _ in range(self.MAX_PAGES):
            response = safe_get(
                client,
                endpoint,
                params={"mode": "json", "skip": skip, "limit": self.PAGE_SIZE},
            )
            data = response.json()
            if not isinstance(data, list):
                raise CollectorError(f"Unexpected Lever response shape from {endpoint}")
            items.extend(data)
            if len(data) < self.PAGE_SIZE:
                return items
            skip += self.PAGE_SIZE
        logger.warning(
            "Lever pagination hit MAX_PAGES=%s cap for %s; results may be incomplete",
            self.MAX_PAGES,
            endpoint,
        )
        return items
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -k lever -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `docker compose run --rm api pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/jose/collectors/lever.py backend/tests/test_collectors_http.py
git commit -m "feat: paginate Lever collection and parse structured salaryRange"
```

---

## Task 5: Wire `jobs_rejected` and raw-payload retention through `collection.py`

**Files:**
- Modify: `backend/jose/config.py`
- Modify: `backend/jose/models/core.py`
- Create: `backend/alembic/versions/0003_source_run_jobs_rejected.py`
- Modify: `backend/jose/services/collection.py`
- Test: `backend/tests/test_collection_service.py`

**Interfaces:**
- Consumes: `SourceRun` from `jose.models` (existing), `CollectedJob`/`CollectionResult` from `jose.collectors.base` (Task 1), `create_source` from `jose.services.sources` (existing), `get_settings` from `jose.config` (existing, gains one field).
- Produces: `Settings.collector_retain_raw_payload: bool` (default `True`); `SourceRun.jobs_rejected: int` (default `0`).

- [ ] **Step 1: Add the config setting**

In `backend/jose/config.py`, replace:

```python
    collector_timeout_seconds: float = 30.0
    collector_user_agent: str = "JOSE-Collector/1.0"
    collector_max_redirects: int = 5
    collector_max_response_bytes: int = 5 * 1024 * 1024
    worker_poll_seconds: float = 2.0
```

with:

```python
    collector_timeout_seconds: float = 30.0
    collector_user_agent: str = "JOSE-Collector/1.0"
    collector_max_redirects: int = 5
    collector_max_response_bytes: int = 5 * 1024 * 1024
    collector_retain_raw_payload: bool = True
    worker_poll_seconds: float = 2.0
```

- [ ] **Step 2: Add the `jobs_rejected` column to the `SourceRun` model**

In `backend/jose/models/core.py`, replace:

```python
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_created: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(150))
```

with:

```python
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_created: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    jobs_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(150))
```

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/0003_source_run_jobs_rejected.py`:

```python
"""Add jobs_rejected to source_runs.

Revision ID: 0003_source_run_jobs_rejected
Revises: 0002_source_import_runs
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_source_run_jobs_rejected"
down_revision = "0002_source_import_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_runs",
        sa.Column("jobs_rejected", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("source_runs", "jobs_rejected", server_default=None)


def downgrade() -> None:
    op.drop_column("source_runs", "jobs_rejected")
```

- [ ] **Step 4: Apply the migration**

Run: `docker compose run --rm api alembic upgrade head`
Expected: migration `0003_source_run_jobs_rejected` applies cleanly with no errors.

- [ ] **Step 5: Write the failing tests**

Create `backend/tests/test_collection_service.py`:

```python
from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.config import get_settings
from jose.models import Job
from jose.schemas import SourceCreate
from jose.services.collection import collect_source
from jose.services.sources import create_source


class _FakeCollector:
    def __init__(self, jobs: list[CollectedJob], rejected_count: int = 0) -> None:
        self._jobs = jobs
        self._rejected_count = rejected_count

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
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
```

- [ ] **Step 6: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collection_service.py -v`
Expected: FAIL — `run.jobs_rejected` raises `AttributeError` (not yet set in `collect_source`); the raw-payload-disabled test fails because `Job.raw_payload` still equals `{"secret": "payload"}` (no toggle logic yet).

- [ ] **Step 7: Wire the new behavior into `collection.py`**

In `backend/jose/services/collection.py`, add the config import — replace:

```python
from jose.collectors.utils import (
    canonicalize_url,
    job_fingerprint,
    normalize_name,
    normalize_title,
    stable_hash,
)
from jose.models import Company, Job, JobSource, JobVersion, Source, SourceRun
```

with:

```python
from jose.collectors.utils import (
    canonicalize_url,
    job_fingerprint,
    normalize_name,
    normalize_title,
    stable_hash,
)
from jose.config import get_settings
from jose.models import Company, Job, JobSource, JobVersion, Source, SourceRun
```

Set `jobs_rejected` on the run — replace:

```python
        run.jobs_found = len(result.jobs)
        run.jobs_created = created
        run.jobs_updated = updated
        source.last_success_at = utcnow()
```

with:

```python
        run.jobs_found = len(result.jobs)
        run.jobs_created = created
        run.jobs_updated = updated
        run.jobs_rejected = result.rejected_count
        source.last_success_at = utcnow()
```

Enforce raw-payload retention centrally in `_upsert_job` — replace:

```python
def _upsert_job(session: Session, source: Source, item: CollectedJob) -> tuple[bool, bool]:
    if not item.application_url:
        raise ValueError(f"Collected job has no application URL: {item.title}")

    company_name = item.company_name.strip() or source.name
```

with:

```python
def _upsert_job(session: Session, source: Source, item: CollectedJob) -> tuple[bool, bool]:
    if not item.application_url:
        raise ValueError(f"Collected job has no application URL: {item.title}")

    raw_payload = item.raw_payload if get_settings().collector_retain_raw_payload else {}
    company_name = item.company_name.strip() or source.name
```

Then use `raw_payload` instead of `item.raw_payload` in both the create and update paths. Replace:

```python
            fingerprint=fingerprint,
            content_hash=content_hash,
            raw_payload=item.raw_payload,
        )
        session.add(job)
```

with:

```python
            fingerprint=fingerprint,
            content_hash=content_hash,
            raw_payload=raw_payload,
        )
        session.add(job)
```

And replace:

```python
            job.content_hash = content_hash
            job.raw_payload = item.raw_payload
            updated = True
```

with:

```python
            job.content_hash = content_hash
            job.raw_payload = raw_payload
            updated = True
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collection_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Run the full suite to check for regressions**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest -q"`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/jose/config.py backend/jose/models/core.py \
  backend/alembic/versions/0003_source_run_jobs_rejected.py \
  backend/jose/services/collection.py backend/tests/test_collection_service.py
git commit -m "feat: record rejected job counts and make raw payload retention configurable"
```

---

## Task 6: Final verification

**Files:** none (verification only)

**Interfaces:** none — this task only runs commands and confirms output.

- [ ] **Step 1: Run the full backend test suite**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest -q"`
Expected: all tests PASS, no errors or warnings about unapplied migrations.

- [ ] **Step 2: Run ruff**

Run: `docker compose run --rm api ruff check jose tests`
Expected: no lint errors. If ruff flags line length or import ordering in any of the new/modified files, fix in place and re-run until clean.

- [ ] **Step 3: Confirm each Issue 04 acceptance criterion has a corresponding test**

Cross-check against `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 04:
- Fixture tests cover empty, paginated, malformed, and changed responses → Tasks 2–4 test files.
- Collector identifies actual company rather than relying solely on source label → Task 3 (`company_name`).
- Compensation parsing is normalized without guessing → Task 4 (`salaryRange`), unchanged Ashby `summaryComponents` handling.
- Publication timestamps are timezone aware → existing `parse_datetime` behavior, exercised by `test_lever_collector_accepts_epoch_milliseconds` and `test_ashby_collector`.
- Jobs lacking application URLs are rejected and logged → Tasks 2–4 rejected-job tests + `logger.warning` calls.
- Raw payload retention can be disabled by configuration → Task 5.

- [ ] **Step 4: Report completion**

No commit needed for this task unless Step 2 required fixes (in which case commit those fixes with message `fix: address ruff findings in ATS collector hardening`).

---

## Out of scope (confirmed with the design spec)

- `JsonLdCollector`'s internal collection logic — only its return type changed (Task 1).
- VC portfolio/aggregator boards (Issue 05/06).
- Changing how `Source.name` is populated at import time.
