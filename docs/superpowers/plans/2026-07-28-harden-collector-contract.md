# Harden the Collector Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every collector adapter (Ashby, Greenhouse, Lever, JSON-LD) one tested, predictable interface per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 03 and `docs/superpowers/specs/2026-07-28-harden-collector-contract-design.md`.

**Architecture:** `CollectedJob` becomes a frozen Pydantic model with a new `CollectorError` subclass taxonomy (`RateLimitError`, `AccessDeniedError`, `UnsafeURLError`). A new `backend/jose/collectors/http.py` module provides `create_http_client()` (bounded timeout, JOSE user-agent, redirect cap, SSRF-blocking transport) and `safe_get()` (streams the response, maps status codes to the error taxonomy, enforces a response-size cap before returning a fully-populated `httpx.Response`). All four adapters swap their inline `httpx.Client(...)` + `client.get(...)` for these shared helpers.

**Tech Stack:** Python 3.12, httpx 0.28, pydantic (via pydantic-settings 2.8), pytest, ruff.

## Global Constraints

- Python 3.12; ruff `target-version = "py312"`, `line-length = 100`, lint rules `["E", "F", "I", "B", "UP", "SIM"]`, `quote-style = "double"` (`backend/pyproject.toml`).
- No live network calls in unit tests — extend the existing fixture/monkeypatch approach in `backend/tests/test_collectors_http.py`. (CLAUDE.md: "Use fixtures for collector tests. Do not make live internet calls in unit tests.")
- A failed collector is a failure, never a successful zero-result run — hardening must raise loudly (via the `CollectorError` taxonomy), never swallow errors into an empty `list[CollectedJob]`. (CLAUDE.md non-negotiable rule 5.)
- Add or update tests with every behavior change (CLAUDE.md working rules).
- No persisted schema changes in this plan, so no Alembic migration is needed.
- Run tests with `docker compose run --rm api pytest <path> -v` (matches `make test`; Colima is already running locally per prior session setup — no local venv exists in `backend/`).
- Run lint with `docker compose run --rm api ruff check jose tests`.

---

### Task 1: Add hardened-HTTP settings

**Files:**
- Modify: `backend/jose/config.py:18` (after `collector_timeout_seconds`)
- Test: Create `backend/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.collector_user_agent: str`, `Settings.collector_max_redirects: int`, `Settings.collector_max_response_bytes: int` — consumed by Task 3's `create_http_client()`/`safe_get()`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config.py`:

```python
from jose.config import Settings


def test_collector_hardening_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.collector_user_agent == "JOSE-Collector/1.0"
    assert settings.collector_max_redirects == 5
    assert settings.collector_max_response_bytes == 5 * 1024 * 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'collector_user_agent'`

- [ ] **Step 3: Add the settings**

Edit `backend/jose/config.py`, replacing:

```python
    collector_timeout_seconds: float = 30.0
    worker_poll_seconds: float = 2.0
```

with:

```python
    collector_timeout_seconds: float = 30.0
    collector_user_agent: str = "JOSE-Collector/1.0"
    collector_max_redirects: int = 5
    collector_max_response_bytes: int = 5 * 1024 * 1024
    worker_poll_seconds: float = 2.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm api pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/jose/config.py backend/tests/test_config.py
git commit -m "feat: add hardened HTTP settings for collectors"
```

---

### Task 2: `CollectedJob` becomes a Pydantic model; add error taxonomy

**Files:**
- Modify: `backend/jose/collectors/base.py` (whole file rewrite)
- Test: Create `backend/tests/test_collected_job.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CollectedJob` (frozen `pydantic.BaseModel`, same field names/types as the current dataclass — `company_name: str`, `title: str`, `application_url: str` required; the rest optional, `raw_payload: dict[str, Any]` default `{}`). New exceptions `RateLimitError(CollectorError)`, `AccessDeniedError(CollectorError)`, `UnsafeURLError(CollectorError)` — consumed by Task 3's `safe_get()`/`SafeHTTPTransport`.

Note: the design spec's phrase "application_url and title stay required str" calls out the two fields with explicit runtime null-checks elsewhere in the codebase (`services/collection.py::_upsert_job` raises `ValueError` if `application_url` is falsy; adapters always supply `title` via an `"Untitled role"` fallback). It does **not** mean `company_name` becomes optional — the spec's leading sentence is "same field names/types it has today," and `services/collection.py:75` calls `item.company_name.strip()` unconditionally, which would raise `AttributeError` on `None`. Keep `company_name: str` required, matching today's dataclass.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_collected_job.py`:

```python
import pytest
from pydantic import ValidationError

from jose.collectors.base import CollectedJob


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collected_job.py -v`
Expected: FAIL — `compensation_min={"not": "a number"}` succeeds today (plain dataclass, no validation), so `test_collected_job_rejects_bad_field_type` fails to raise; `test_collected_job_is_frozen` fails because plain `@dataclass(slots=True)` (not frozen) allows attribute assignment.

- [ ] **Step 3: Rewrite `base.py`**

Replace the full contents of `backend/jose/collectors/base.py`:

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

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collected_job.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing collector test suite to check for regressions**

Run: `docker compose run --rm api pytest tests/test_collectors.py tests/test_collectors_http.py -v`
Expected: PASS — adapters construct `CollectedJob(...)` via keyword args exactly as before, so the dataclass→BaseModel swap is a drop-in replacement at this point (adapters and their `httpx.Client` usage aren't touched until Task 4).

- [ ] **Step 6: Commit**

```bash
git add backend/jose/collectors/base.py backend/tests/test_collected_job.py
git commit -m "feat: make CollectedJob a validated Pydantic model with an error taxonomy"
```

---

### Task 3: Shared hardened HTTP client with SSRF protection

**Files:**
- Create: `backend/jose/collectors/http.py`
- Test: Create `backend/tests/test_collector_http_hardening.py`

**Interfaces:**
- Consumes: `Settings.collector_user_agent`, `.collector_max_redirects`, `.collector_max_response_bytes`, `.collector_timeout_seconds` (Task 1); `CollectorError`, `RateLimitError`, `AccessDeniedError`, `UnsafeURLError` (Task 2).
- Produces: `create_http_client() -> httpx.Client`, `safe_get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response`, `SafeHTTPTransport(httpx.HTTPTransport)` — consumed by Task 4's adapter migration.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_collector_http_hardening.py`:

```python
import socket
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from jose.collectors.base import AccessDeniedError, CollectorError, RateLimitError, UnsafeURLError
from jose.collectors.http import SafeHTTPTransport, safe_get
from jose.config import get_settings


def _addrinfo(ip: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def test_transport_blocks_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("10.0.0.5"))
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://internal.example.com/")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


def test_transport_blocks_loopback_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("127.0.0.1"))
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://internal.example.com/")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


def test_transport_allows_public_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("93.184.216.34"))
    expected = httpx.Response(200, request=httpx.Request("GET", "https://example.com/"))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, request: expected)
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://example.com/")
    assert transport.handle_request(request) is expected


def test_transport_rejects_non_http_scheme() -> None:
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "file:///etc/passwd")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


class _FakeStreamResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers({})
        self._body = body
        self.request = httpx.Request("GET", "https://example.com/jobs")

    def iter_bytes(self) -> Iterator[bytes]:
        chunk_size = 64
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


class _FakeStreamClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    @contextmanager
    def stream(self, method: str, url: str, **_: object) -> Iterator[_FakeStreamResponse]:
        yield self._response


def test_safe_get_maps_429_to_rate_limit_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(429, b"{}"))
    with pytest.raises(RateLimitError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_maps_401_to_access_denied_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(401, b"{}"))
    with pytest.raises(AccessDeniedError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_maps_403_to_access_denied_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(403, b"{}"))
    with pytest.raises(AccessDeniedError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_maps_other_4xx_to_collector_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(418, b"{}"))
    with pytest.raises(CollectorError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_enforces_response_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "collector_max_response_bytes", 10)
    client = _FakeStreamClient(_FakeStreamResponse(200, b"x" * 1000))
    with pytest.raises(CollectorError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_returns_full_response_on_success() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(200, b'{"ok": true}'))
    response = safe_get(client, "https://example.com/jobs")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collector_http_hardening.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jose.collectors.http'`

- [ ] **Step 3: Create `backend/jose/collectors/http.py`**

```python
import ipaddress
import socket
from typing import Any

import httpx

from jose.collectors.base import AccessDeniedError, CollectorError, RateLimitError, UnsafeURLError
from jose.config import get_settings


class SafeHTTPTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme not in ("http", "https"):
            raise UnsafeURLError(f"Unsafe URL scheme: {url.scheme}")

        host = url.host
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise UnsafeURLError(f"Unable to resolve host: {host}") from exc

        for _family, _type, _proto, _canonname, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_loopback
                or ip.is_private
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_reserved
            ):
                raise UnsafeURLError(f"Refusing to contact unsafe host: {host} ({ip})")

        return super().handle_request(request)


def create_http_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=settings.collector_timeout_seconds,
        follow_redirects=True,
        max_redirects=settings.collector_max_redirects,
        headers={"User-Agent": settings.collector_user_agent},
        transport=SafeHTTPTransport(),
    )


def safe_get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    max_bytes = get_settings().collector_max_response_bytes

    with client.stream("GET", url, **kwargs) as response:
        if response.status_code == 429:
            raise RateLimitError(f"Rate limited by {url}")
        if response.status_code in (401, 403):
            raise AccessDeniedError(f"Access denied by {url}: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise CollectorError(f"Request to {url} failed with status {response.status_code}")

        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise CollectorError(f"Response from {url} exceeded {max_bytes} bytes")

        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=bytes(body),
            request=response.request,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collector_http_hardening.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/jose/collectors/http.py backend/tests/test_collector_http_hardening.py
git commit -m "feat: add SSRF-safe HTTP client and error-taxonomy-aware safe_get"
```

---

### Task 4: Migrate all four adapters to the hardened HTTP client

**Files:**
- Modify: `backend/jose/collectors/ashby.py`
- Modify: `backend/jose/collectors/greenhouse.py`
- Modify: `backend/jose/collectors/lever.py`
- Modify: `backend/jose/collectors/jsonld.py`
- Modify: `backend/tests/test_collectors_http.py` (fake client/response grow a `.stream()` mode)

**Interfaces:**
- Consumes: `create_http_client()`, `safe_get()` (Task 3).
- Produces: nothing new — adapters keep their existing `Collector.collect(...)` signature and return `list[CollectedJob]` unchanged; `services/collection.py` requires no changes (it only does attribute access on `CollectedJob`, per the design spec's "Out of scope").

- [ ] **Step 1: Update the test fakes and rewrite the adapter tests to expect the new call pattern**

Replace the top of `backend/tests/test_collectors_http.py` (imports through `patch_client`) with:

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
```

Leave the four `test_*_collector*` functions below unchanged — they already call `patch_client(monkeypatch, "jose.collectors.<adapter>", FakeResponse(...))` and assert on `jobs[0]...`, which continues to work once `patch_client` targets `create_http_client` instead of `httpx.Client`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -v`
Expected: FAIL — `AttributeError: <module 'jose.collectors.ashby'> does not have the attribute 'create_http_client'` (adapters haven't been migrated yet).

- [ ] **Step 3: Migrate `ashby.py`**

Replace the full contents of `backend/jose/collectors/ashby.py`:

```python
from urllib.parse import urlsplit

from jose.collectors.base import CollectedJob, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class AshbyCollector:
    name = "ashby"

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]:
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
        return jobs
```

- [ ] **Step 4: Migrate `greenhouse.py`**

Replace the full contents of `backend/jose/collectors/greenhouse.py`:

```python
from urllib.parse import parse_qs, urlsplit

from jose.collectors.base import CollectedJob, CollectorError
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

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]:
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
        return jobs
```

- [ ] **Step 5: Migrate `lever.py`**

Replace the full contents of `backend/jose/collectors/lever.py`:

```python
from urllib.parse import urlsplit

from jose.collectors.base import CollectedJob, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class LeverCollector:
    name = "lever"

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]:
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
        return jobs
```

- [ ] **Step 6: Migrate `jsonld.py`**

Replace the full contents of `backend/jose/collectors/jsonld.py`:

```python
import json
from collections.abc import Iterable
from typing import Any

from bs4 import BeautifulSoup

from jose.collectors.base import CollectedJob, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class JsonLdCollector:
    name = "jsonld"

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]:
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
        return jobs

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

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collectors_http.py -v`
Expected: PASS

- [ ] **Step 8: Run the full backend test suite**

Run: `docker compose run --rm api pytest`
Expected: PASS (all pre-existing and new tests green)

- [ ] **Step 9: Run ruff**

Run: `docker compose run --rm api ruff check jose tests`
Expected: no findings (unused `httpx`/`get_settings` imports must be fully removed from all four adapter files — ruff's `F` rule set catches unused imports).

- [ ] **Step 10: Commit**

```bash
git add backend/jose/collectors/ashby.py backend/jose/collectors/greenhouse.py \
  backend/jose/collectors/lever.py backend/jose/collectors/jsonld.py \
  backend/tests/test_collectors_http.py
git commit -m "feat: migrate all collector adapters to the hardened HTTP client"
```

---

## Post-plan verification

- [ ] Re-read `docs/superpowers/specs/2026-07-28-harden-collector-contract-design.md` acceptance criteria against the four tasks above — all six criteria are covered: Pydantic validation (Task 2), bounded timeouts/user-agent/redirects/size limits (Tasks 1 & 3), SSRF rejection (Task 3), rate-limit/access-denied distinction (Tasks 2 & 3), unknown fields null (Task 2), no live network calls in tests (Tasks 3 & 4 use fakes throughout).
- [ ] Confirm `backend/jose/services/collection.py` was not modified (out of scope per spec) and still passes its existing tests: `docker compose run --rm api pytest tests/test_sources_service.py -v`.
