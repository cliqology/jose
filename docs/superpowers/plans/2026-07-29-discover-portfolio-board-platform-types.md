# Discover Portfolio-Board Platform Types (Issue 05) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every VC-portfolio source (`category="vc_portfolio"`) a real, reviewable platform classification — a matched collector adapter or an explicit `"unsupported"` status — instead of the silent `"jsonld"` fallback that `detect_adapter` currently produces for any unrecognized host, and document the findings in `docs/source-catalog.md`.

**Architecture:** A new `backend/jose/services/platform_detection.py` module does a single safe HTTP GET per VC source (reusing the existing SSRF-safe `create_http_client`/`safe_get`), classifies the result (known ATS host → JSON-LD structured data → known aggregator signature → uncertain → error), persists the result onto four new nullable columns on `Source` plus the existing `adapter`/`last_error` columns, and renders a markdown catalog from that DB state. A thin Typer CLI command orchestrates a full run.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Alembic, httpx, BeautifulSoup4, Pydantic, Typer, pytest — all already in `backend/requirements.txt`, no new dependencies.

## Global Constraints

- Never submit an application or send an external message without approval — not implicated here (read-only GETs, no messaging).
- Unknown information remains unknown — a source that can't be confidently classified is `"uncertain"`, never coerced into `"supported"` or a confident `"unsupported"`.
- A failed collector is a failure, never a successful zero-result run — a probe HTTP failure is `detection_status="error"`, distinct from `"uncertain"`, and never silently written as `"unsupported"`.
- Every user-owned record includes `user_id` — all queries in this plan filter by `Source.user_id == user.id`.
- Every task must be idempotent and safely retryable — `detect-vc-platforms` can be re-run any number of times; each run fully overwrites the prior detection result and the catalog file.
- Use timezone-aware UTC datetimes — `detected_at` uses the existing `utcnow()` helper (`jose.models.base`), matching `last_attempt_at`/`last_success_at`.
- Use UUID primary keys — `Source.id` already is one; unchanged here.
- Do not put business logic in route handlers — all detection logic lives in `services/platform_detection.py`; the CLI command is a thin wrapper (no new API route in this plan).
- Use typed Pydantic schemas at API boundaries — `ProbeOutcome`/`ProbeResult` are frozen Pydantic models; `SourceRead` is extended (typed) to expose the new columns.
- Use fixtures/monkeypatching for HTTP; no live network calls in unit tests — matches the `FakeResponse`/`FakeClient` pattern in `backend/tests/test_collectors_http.py`.
- Add a migration whenever the persisted schema changes — Task 1 adds one.
- Ruff must pass (`select = ["E", "F", "I", "B", "UP", "SIM"]`, line length 100, double quotes) for all new/changed Python.

---

## File Structure

- **Modify** `backend/jose/models/core.py` — add 4 columns to `Source`.
- **Modify** `backend/jose/schemas.py` — add `SourceAdapter.UNSUPPORTED`; add 4 fields to `SourceRead`.
- **Create** `backend/alembic/versions/0004_source_platform_detection.py` — migration for the 4 new columns.
- **Modify** `backend/jose/collectors/registry.py` — extract `match_known_ats_host()` so both `detect_adapter` and the new detection service share one hostname table.
- **Create** `backend/jose/services/platform_detection.py` — `ProbeOutcome`, `ProbeResult`, `probe_source()`, `detect_platforms_for_vc_sources()`, `render_source_catalog()`.
- **Modify** `backend/jose/cli.py` — add `detect-vc-platforms` command.
- **Modify** `docker-compose.yml` — mount `./docs:/docs` on the `api` service so the CLI command can write the repo-root catalog file from inside the container.
- **Modify** `Makefile` — add a `detect-vc-platforms` target mirroring the existing `import-sources` target.
- **Modify** `backend/tests/test_sources_service.py` — cover the new `SourceRead` fields and `SourceAdapter.UNSUPPORTED`.
- **Modify** `backend/tests/test_collectors.py` — cover `match_known_ats_host()`.
- **Create** `backend/tests/test_platform_detection.py` — cover `probe_source`, `detect_platforms_for_vc_sources`, `render_source_catalog`.

---

### Task 1: Add platform-detection columns to `Source`, migration, and schema support

**Files:**
- Modify: `backend/jose/models/core.py:37-49` (the `Source` class body, right after `last_error`)
- Modify: `backend/jose/schemas.py:17-22` (`SourceAdapter`) and `backend/jose/schemas.py:58-72` (`SourceRead`)
- Create: `backend/alembic/versions/0004_source_platform_detection.py`
- Test: `backend/tests/test_sources_service.py`

**Interfaces:**
- Produces: `Source.detected_platform: str | None`, `Source.detection_status: str | None`, `Source.detected_application_url: str | None`, `Source.detected_at: datetime | None` — used by Task 4 (`detect_platforms_for_vc_sources`) and Task 5 (`render_source_catalog`). `SourceAdapter.UNSUPPORTED = "unsupported"` — used by Task 4 when writing `Source.adapter`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_sources_service.py` (existing imports at the top already include `SourceCreate`, `SourceUpdate`, `create_source`, `update_source` — add `SourceAdapter`, `SourceCategory` to the `from jose.schemas import ...` line, and `SourceRead`):

```python
def test_update_source_can_mark_adapter_unsupported(db_session, user):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme3.example.com/jobs")
    )

    updated = update_source(
        db_session, user, source.id, SourceUpdate(adapter=SourceAdapter.UNSUPPORTED)
    )

    assert updated.adapter == "unsupported"


def test_source_read_exposes_detection_fields(db_session, user):
    source = create_source(
        db_session,
        user,
        SourceCreate(
            name="Example VC",
            url="https://jobs.examplevc.com/",
            category=SourceCategory.VC_PORTFOLIO,
        ),
    )
    source.detected_platform = "getro"
    source.detection_status = "unsupported"
    source.detected_application_url = "https://jobs.examplevc.com/board"
    from jose.models.base import utcnow

    source.detected_at = utcnow()
    db_session.commit()
    db_session.refresh(source)

    read = SourceRead.model_validate(source)

    assert read.detected_platform == "getro"
    assert read.detection_status == "unsupported"
    assert read.detected_application_url == "https://jobs.examplevc.com/board"
    assert read.detected_at is not None
```

(Move the `from jose.models.base import utcnow` import to the top of the test file alongside the other imports rather than inline — inline is shown here only to make the diff obvious.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_sources_service.py -v -k "unsupported or detection_fields"`
Expected: FAIL — `SourceAdapter` has no `UNSUPPORTED` member, and `Source`/`SourceRead` have no `detected_platform` attribute.

- [ ] **Step 3: Add the columns to the `Source` model**

In `backend/jose/models/core.py`, immediately after the existing `last_error` line:

```python
    last_error: Mapped[str | None] = mapped_column(Text)
    detected_platform: Mapped[str | None] = mapped_column(String(100))
    detection_status: Mapped[str | None] = mapped_column(String(20))
    detected_application_url: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Add `UNSUPPORTED` to `SourceAdapter` and extend `SourceRead`**

In `backend/jose/schemas.py`:

```python
class SourceAdapter(StrEnum):
    AUTO = "auto"
    ASHBY = "ashby"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    JSONLD = "jsonld"
    UNSUPPORTED = "unsupported"
```

And in `SourceRead`, after the existing `last_error: str | None` line:

```python
    last_error: str | None
    detected_platform: str | None
    detection_status: str | None
    detected_application_url: str | None
    detected_at: datetime | None
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/0004_source_platform_detection.py`:

```python
"""Add platform detection fields to sources.

Revision ID: 0004_source_platform_detection
Revises: 0003_source_run_jobs_rejected
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_source_platform_detection"
down_revision = "0003_source_run_jobs_rejected"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("detected_platform", sa.String(length=100), nullable=True))
    op.add_column("sources", sa.Column("detection_status", sa.String(length=20), nullable=True))
    op.add_column("sources", sa.Column("detected_application_url", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "detected_at")
    op.drop_column("sources", "detected_application_url")
    op.drop_column("sources", "detection_status")
    op.drop_column("sources", "detected_platform")
```

- [ ] **Step 6: Apply the migration and run the tests**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest tests/test_sources_service.py -v"`
Expected: all tests in the file PASS, including the two new ones.

- [ ] **Step 7: Commit**

```bash
git add backend/jose/models/core.py backend/jose/schemas.py \
  backend/alembic/versions/0004_source_platform_detection.py \
  backend/tests/test_sources_service.py
git commit -m "feat: add platform detection columns to sources"
```

---

### Task 2: Extract a shared known-ATS-host matcher in the collector registry

**Files:**
- Modify: `backend/jose/collectors/registry.py`
- Test: `backend/tests/test_collectors.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `match_known_ats_host(host: str) -> str | None` — used by Task 3's `probe_source`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_collectors.py` (extend the existing `from jose.collectors.registry import detect_adapter` line to also import `match_known_ats_host`):

```python
def test_match_known_ats_host() -> None:
    assert match_known_ats_host("boards.greenhouse.io") == "greenhouse"
    assert match_known_ats_host("job-boards.greenhouse.io") == "greenhouse"
    assert match_known_ats_host("JOBS.LEVER.CO") == "lever"
    assert match_known_ats_host("jobs.ashbyhq.com") == "ashby"
    assert match_known_ats_host("example.com") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_collectors.py -v -k match_known_ats_host`
Expected: FAIL with `ImportError: cannot import name 'match_known_ats_host'`.

- [ ] **Step 3: Refactor `registry.py`**

Replace the body of `backend/jose/collectors/registry.py` from `def detect_adapter` onward with:

```python
_ATS_HOSTS: dict[str, str] = {
    "jobs.ashbyhq.com": "ashby",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
}


def match_known_ats_host(host: str) -> str | None:
    return _ATS_HOSTS.get(host.lower())


def detect_adapter(source_url: str, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    host = urlsplit(source_url).netloc.lower()
    return match_known_ats_host(host) or "jsonld"


def get_collector(source_url: str, requested: str = "auto") -> Collector:
    adapter = detect_adapter(source_url, requested)
    collector = COLLECTORS.get(adapter)
    if collector is None:
        raise UnsupportedSourceError(f"Unsupported collector adapter: {adapter}")
    return collector
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collectors.py -v`
Expected: all PASS, including the pre-existing `test_detect_adapter` (unchanged behavior — this is a pure refactor).

- [ ] **Step 5: Commit**

```bash
git add backend/jose/collectors/registry.py backend/tests/test_collectors.py
git commit -m "refactor: extract shared known-ATS-host matcher from detect_adapter"
```

---

### Task 3: `probe_source` — classify a single VC source

**Files:**
- Create: `backend/jose/services/platform_detection.py`
- Test: `backend/tests/test_platform_detection.py`

**Interfaces:**
- Consumes: `create_http_client`/`safe_get` (`jose.collectors.http`), `CollectorError` (`jose.collectors.base`), `match_known_ats_host` (`jose.collectors.registry`, Task 2).
- Produces: `AGGREGATOR_SIGNATURES: dict[str, str]`, `ProbeOutcome` (fields: `status: Literal["supported","unsupported","uncertain","error"]`, `adapter: str | None`, `detected_platform: str | None`, `detected_application_url: str | None`, `error: str | None`), `probe_source(url: str) -> ProbeOutcome` — used by Task 4.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_platform_detection.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_platform_detection.py -v`
Expected: FAIL — `jose.services.platform_detection` does not exist yet.

- [ ] **Step 3: Implement `platform_detection.py`**

Create `backend/jose/services/platform_detection.py`:

```python
import json
from typing import Any, Literal
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

from jose.collectors.base import CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.registry import match_known_ats_host

AGGREGATOR_SIGNATURES: dict[str, str] = {
    "getro.com": "getro",
}

DetectionStatus = Literal["supported", "unsupported", "uncertain", "error"]


class ProbeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DetectionStatus
    adapter: str | None
    detected_platform: str | None
    detected_application_url: str | None
    error: str | None


def _has_job_posting(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("@type") == "JobPosting":
            return True
        graph = value.get("@graph")
        if graph and _has_job_posting(graph):
            return True
        return any(
            _has_job_posting(child)
            for key, child in value.items()
            if key != "@graph" and isinstance(child, (dict, list))
        )
    if isinstance(value, list):
        return any(_has_job_posting(item) for item in value)
    return False


def _contains_json_ld_job_posting(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(tag.string or tag.get_text())
        except json.JSONDecodeError:
            continue
        if _has_job_posting(parsed):
            return True
    return False


def _match_aggregator_signature(host: str, html: str) -> str | None:
    for needle, platform in AGGREGATOR_SIGNATURES.items():
        if needle in host or needle in html:
            return platform
    return None


def probe_source(url: str) -> ProbeOutcome:
    try:
        with create_http_client() as client:
            response = safe_get(client, url)
    except CollectorError as exc:
        return ProbeOutcome(
            status="error",
            adapter=None,
            detected_platform=None,
            detected_application_url=None,
            error=str(exc),
        )

    final_url = str(response.url)
    host = urlsplit(final_url).netloc.lower()
    html = response.text

    matched_adapter = match_known_ats_host(host)
    if matched_adapter:
        return ProbeOutcome(
            status="supported",
            adapter=matched_adapter,
            detected_platform=matched_adapter,
            detected_application_url=final_url,
            error=None,
        )

    if _contains_json_ld_job_posting(html):
        return ProbeOutcome(
            status="supported",
            adapter="jsonld",
            detected_platform="jsonld",
            detected_application_url=final_url,
            error=None,
        )

    aggregator = _match_aggregator_signature(host, html)
    if aggregator:
        return ProbeOutcome(
            status="unsupported",
            adapter="unsupported",
            detected_platform=aggregator,
            detected_application_url=final_url,
            error=None,
        )

    return ProbeOutcome(
        status="uncertain",
        adapter="unsupported",
        detected_platform=None,
        detected_application_url=final_url,
        error=None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_platform_detection.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/jose/services/platform_detection.py backend/tests/test_platform_detection.py
git commit -m "feat: add probe_source platform classification for VC sources"
```

---

### Task 4: `detect_platforms_for_vc_sources` — orchestrate and persist

**Files:**
- Modify: `backend/jose/services/platform_detection.py`
- Test: `backend/tests/test_platform_detection.py`

**Interfaces:**
- Consumes: `probe_source`, `ProbeOutcome` (Task 3); `Source`, `User` (`jose.models`); `utcnow` (`jose.models.base`).
- Produces: `ProbeResult` (fields: `source_id: uuid.UUID`, `source_name: str`, plus all `ProbeOutcome` fields), `detect_platforms_for_vc_sources(session: Session, user: User) -> list[ProbeResult]` — used by Task 5 (via DB state) and Task 6 (CLI).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_platform_detection.py` (add these imports at the top: `from sqlalchemy import select`, `from jose.models import Source`, `from jose.schemas import SourceCategory, SourceCreate`, `from jose.services.platform_detection import ProbeOutcome, detect_platforms_for_vc_sources`, `from jose.services.sources import create_source`):

```python
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


def test_detect_platforms_records_error_without_overwriting_adapter(db_session, user, monkeypatch):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_platform_detection.py -v -k detect_platforms`
Expected: FAIL — `detect_platforms_for_vc_sources` does not exist yet.

- [ ] **Step 3: Implement the orchestrator**

Append to `backend/jose/services/platform_detection.py` (add `import uuid` at the top alongside the other stdlib imports, and add `from sqlalchemy import select`, `from sqlalchemy.orm import Session`, `from jose.models import Source, User`, `from jose.models.base import utcnow` to the imports):

```python
class ProbeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    source_name: str
    status: DetectionStatus
    adapter: str | None
    detected_platform: str | None
    detected_application_url: str | None
    error: str | None


def detect_platforms_for_vc_sources(session: Session, user: User) -> list[ProbeResult]:
    sources = list(
        session.scalars(
            select(Source).where(Source.user_id == user.id, Source.category == "vc_portfolio")
        ).all()
    )

    results: list[ProbeResult] = []
    for source in sources:
        outcome = probe_source(source.url)
        if outcome.status != "error":
            source.adapter = outcome.adapter
        else:
            source.last_error = outcome.error
        source.detected_platform = outcome.detected_platform
        source.detection_status = outcome.status
        source.detected_application_url = outcome.detected_application_url
        source.detected_at = utcnow()
        results.append(
            ProbeResult(
                source_id=source.id,
                source_name=source.name,
                status=outcome.status,
                adapter=outcome.adapter,
                detected_platform=outcome.detected_platform,
                detected_application_url=outcome.detected_application_url,
                error=outcome.error,
            )
        )

    session.commit()
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_platform_detection.py -v`
Expected: all tests PASS (5 from Task 3 + 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/jose/services/platform_detection.py backend/tests/test_platform_detection.py
git commit -m "feat: orchestrate and persist VC platform detection results"
```

---

### Task 5: `render_source_catalog` — generate `docs/source-catalog.md` content

**Files:**
- Modify: `backend/jose/services/platform_detection.py`
- Test: `backend/tests/test_platform_detection.py`

**Interfaces:**
- Consumes: `Source`, `User`, `select`, `Session` (already imported by Task 4).
- Produces: `render_source_catalog(session: Session, user: User) -> str` — used by Task 6 (CLI).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_platform_detection.py` (add `from jose.services.platform_detection import render_source_catalog` to the existing import line):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_platform_detection.py -v -k render_source_catalog`
Expected: FAIL — `render_source_catalog` does not exist yet.

- [ ] **Step 3: Implement `render_source_catalog`**

Append to `backend/jose/services/platform_detection.py`:

```python
def render_source_catalog(session: Session, user: User) -> str:
    sources = list(
        session.scalars(
            select(Source)
            .where(Source.user_id == user.id, Source.category == "vc_portfolio")
            .order_by(Source.name)
        ).all()
    )

    lines = [
        "# Source Catalog: VC Portfolio Boards",
        "",
        "Generated by `python -m jose.cli detect-vc-platforms`. The table below is "
        "overwritten on every run — add manual research findings in the Notes section "
        "at the bottom instead.",
        "",
        "| Source | Configured URL | Detected Platform | Adapter / Status | "
        "Detected Application URL |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source in sources:
        status = source.detection_status or "not probed"
        platform = source.detected_platform or "—"
        app_url = source.detected_application_url or "—"
        lines.append(
            f"| {source.name} | {source.url} | {platform} | "
            f"{source.adapter} / {status} | {app_url} |"
        )
    lines.extend(["", "## Notes", "", "_Add manual research findings here._"])
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_platform_detection.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/jose/services/platform_detection.py backend/tests/test_platform_detection.py
git commit -m "feat: render VC source catalog as markdown"
```

---

### Task 6: CLI command, container wiring, and Makefile target

**Files:**
- Modify: `backend/jose/cli.py`
- Modify: `docker-compose.yml`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `detect_platforms_for_vc_sources`, `render_source_catalog` (Tasks 4–5).
- Produces: `detect-vc-platforms` CLI command (no other task depends on this — it's the final entry point).

There is no existing precedent for automated tests of CLI commands in this codebase (`seed`, `import-sources`, `collect-source`, `enqueue-collect-all`, `worker` all have none — they're thin wrappers over already-tested service functions). This task follows that convention; verification is manual (Step 4).

- [ ] **Step 1: Add the CLI command**

In `backend/jose/cli.py`, add this import alongside the existing `jose.services.*` imports:

```python
from jose.services.platform_detection import detect_platforms_for_vc_sources, render_source_catalog
```

Add the command (placed after `import_sources`, before `collect_source_command`, to keep source-management commands grouped):

```python
@app.command("detect-vc-platforms")
def detect_vc_platforms(catalog_path: Path = Path("docs/source-catalog.md")) -> None:
    """Probe VC portfolio sources and record their platform/adapter status."""
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        results = detect_platforms_for_vc_sources(session, user)
        catalog_text = render_source_catalog(session, user)
    catalog_path.write_text(catalog_text)
    for result in results:
        if result.status == "error":
            typer.echo(f"  ERROR      {result.source_name}: {result.error}")
        else:
            typer.echo(
                f"  {result.status.upper():<10} {result.source_name}: "
                f"adapter={result.adapter} platform={result.detected_platform}"
            )
    typer.echo(f"Wrote {catalog_path}")
```

- [ ] **Step 2: Mount `docs/` into the `api` container**

The `api` service in `docker-compose.yml` currently mounts only `./backend:/app` and `./data:/data` — the repo-root `docs/` directory (where `docs/PRD.md` and `docs/backlog/` already live) is not visible inside the container, so writing to a relative `docs/source-catalog.md` path from inside `api` would land in `backend/docs/` instead. Add a third volume line to the `api` service:

```yaml
  api:
    ...
    volumes:
      - ./backend:/app
      - ./data:/data
      - ./docs:/docs
```

- [ ] **Step 3: Add the Makefile target**

In `Makefile`, add `detect-vc-platforms` to the `.PHONY` line, and add the target after `import-sources`:

```makefile
detect-vc-platforms:
	docker compose run --rm api python -m jose.cli detect-vc-platforms /docs/source-catalog.md
```

- [ ] **Step 4: Manually verify the full wiring**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest"`
Expected: full test suite PASSES (this confirms nothing in Tasks 1–5 regressed).

Run: `docker compose run --rm api ruff check jose tests`
Expected: no errors.

Then, with at least one `vc_portfolio` source seeded (via `make import-sources` if not already done):

Run: `make detect-vc-platforms`
Expected: one status line per VC source is printed, and `docs/source-catalog.md` is created/updated on the host (visible via `cat docs/source-catalog.md` from the repo root, not just inside the container) with a row per VC source.

- [ ] **Step 5: Commit**

```bash
git add backend/jose/cli.py docker-compose.yml Makefile
git commit -m "feat: add detect-vc-platforms CLI command"
```

---

## Manual follow-up after implementation (not part of automated task execution)

Per the design spec's "Closing out the issue" section: running `make detect-vc-platforms` once against the real 17 VC sources is a live action that makes outbound HTTP requests to third-party sites. Do not run it as an unattended step — Scott should run it (or explicitly ask for it to be run), review the generated `docs/source-catalog.md`, and:

1. Re-run `make detect-vc-platforms` for any source left in `"error"` status (transient failures).
2. Manually research any source still `"uncertain"` after that, and update its `adapter` via the existing source CRUD (Issue 01) plus a note in the catalog's `## Notes` section.
3. Consider adding entries to `AGGREGATOR_SIGNATURES` in `platform_detection.py` if the same non-ATS platform shows up across multiple sources — with a follow-up commit and test, not silently.

The issue is only done once no VC source remains on `adapter="auto"` or `detection_status="error"`.

---

## Self-Review Notes

- **Spec coverage:** every acceptance criterion maps to a task — configured-adapter-or-unsupported (Tasks 1, 4), stored-and-reviewable (Task 1's `SourceRead` fields + Task 5's catalog), redirected-ATS-links-as-canonical-URL (Task 3's `detected_application_url`), documented-in-source-catalog.md (Tasks 5–6), no-silent-jsonld (Task 3's ordered classification, JSON-LD only on actual match).
- **Placeholder scan:** none — every step has literal code, exact file paths, and runnable commands.
- **Type consistency:** `ProbeOutcome`/`ProbeResult` field names and the `DetectionStatus` literal are introduced once in Task 3 and reused verbatim in Tasks 4–6; `Source` column names introduced in Task 1 are reused verbatim in Tasks 4–5.
