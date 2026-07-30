# Source Health Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every source a health view — last attempt/success/duration/counts/adapter/error, a rerun action, run history, repeated-failure highlighting, zero-result-vs-failure distinction, and secret-sanitized error text — satisfying Issue 10 in `docs/backlog/PHASE_0_1_BACKLOG.md`.

**Architecture:** Almost all the data already exists (`Source` fields, `SourceRun` table). This plan adds one new persisted counter (`Source.consecutive_failures`), one new read-only endpoint (`GET /api/v1/sources/{id}/runs`), an error-redaction utility applied inside `collect_source()`, and a new `/sources/[id]` detail page plus small updates to the existing sources list.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Pydantic (backend, Python), Next.js App Router + TypeScript (frontend). Tests: pytest against a real Postgres DB (`make test` runs `alembic upgrade head && pytest` inside the `api` container). No frontend test runner — `npm run lint` and `npm run build` are the frontend gates.

## Global Constraints

- Never submit an application or send an external message without explicit user approval. (N/A to this feature — no user-facing writes beyond source config.)
- Every user-owned record includes `user_id`. `SourceRun` already does; no new user-owned tables are added.
- A failed collector run is a failure, never a successful zero-result run — the UI must show these as visually distinct states, not conflate them.
- Do not log secrets, résumés, email bodies, browser cookies, or OAuth tokens. Error text written to `SourceRun.error_message` / `Source.last_error` must be sanitized first.
- Add a migration whenever the persisted schema changes.
- Use typed Pydantic schemas at API boundaries.
- Use timezone-aware UTC datetimes (existing `utcnow()` helpers already do this — reuse them).
- Do not put business logic in route handlers — ownership checks and queries belong in `jose/services/*`.
- Ruff must pass for Python. Next.js lint/build must pass for frontend changes.
- Use fixtures for collector tests; no live internet calls in unit tests (not applicable here — no collector code changes).

---

### Task 1: Add `consecutive_failures` column to `Source`

**Files:**
- Modify: `backend/jose/models/core.py:53` (Source model, after `last_error`)
- Create: `backend/alembic/versions/0008_source_health_dashboard.py`

**Interfaces:**
- Produces: `Source.consecutive_failures: int` (default `0`, `nullable=False`) — consumed by Task 3 (`collect_source`) and Task 5 (`SourceRead` schema / frontend).

- [ ] **Step 1: Add the column to the model**

In `backend/jose/models/core.py`, in the `Source` class, add this line immediately after the existing `last_error` field (line 53):

```python
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
```

(`Integer` is already imported at the top of this file.)

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/0008_source_health_dashboard.py`:

```python
"""Add consecutive_failures counter to sources.

Revision ID: 0008_source_health_dashboard
Revises: 0007_harden_task_queue
Create Date: 2026-07-30
"""

from alembic import op  # noqa: I001
import sqlalchemy as sa

revision = "0008_source_health_dashboard"
down_revision = "0007_harden_task_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("sources", "consecutive_failures")
```

- [ ] **Step 3: Apply the migration and confirm the existing suite still passes**

Run: `make migrate`
Expected: migration `0008_source_health_dashboard` applies cleanly with no errors.

Run: `make test`
Expected: PASS (no behavior changed yet — this just confirms the new column doesn't break anything, e.g. `SourceRead.model_validate` / existing fixtures).

- [ ] **Step 4: Commit**

```bash
git add backend/jose/models/core.py backend/alembic/versions/0008_source_health_dashboard.py
git commit -m "feat: add consecutive_failures counter to sources"
```

---

### Task 2: Error text sanitizer

**Files:**
- Create: `backend/jose/services/error_sanitizer.py`
- Test: `backend/tests/test_error_sanitizer.py`

**Interfaces:**
- Produces: `sanitize_error_text(text: str) -> str` — consumed by Task 3 (`collect_source`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_error_sanitizer.py`:

```python
from jose.services.error_sanitizer import sanitize_error_text


def test_redacts_secret_query_string_params():
    text = "GET https://ats.example.com/jobs?token=abc123&page=2 -> 403 Forbidden"

    result = sanitize_error_text(text)

    assert "abc123" not in result
    assert "token=[redacted]" in result
    assert "page=2" in result


def test_redacts_authorization_header_with_scheme():
    text = "Request failed with headers Authorization: Bearer sk-live-abcdef123456 and Accept: */*"

    result = sanitize_error_text(text)

    assert "sk-live-abcdef123456" not in result
    assert "Authorization: Bearer [redacted]" in result
    assert "Accept: */*" in result


def test_redacts_authorization_header_without_scheme():
    text = "Authorization: abc123xyz"

    result = sanitize_error_text(text)

    assert "abc123xyz" not in result
    assert result == "Authorization: [redacted]"


def test_redacts_cookie_header():
    text = "Cookie: session_id=abc123; csrf=xyz789"

    result = sanitize_error_text(text)

    assert "abc123" not in result
    assert "xyz789" not in result
    assert result == "Cookie: [redacted]"


def test_redacts_userinfo_in_url():
    text = "Connection refused: https://user:s3cr3t@internal.example.com/api"

    result = sanitize_error_text(text)

    assert "s3cr3t" not in result
    assert "https://[redacted]@internal.example.com/api" in result


def test_leaves_non_secret_text_unchanged():
    text = "ConnectionError: timed out after 30s contacting https://boards.example.com/jobs?page=2"

    assert sanitize_error_text(text) == text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_error_sanitizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jose.services.error_sanitizer'`

- [ ] **Step 3: Implement the sanitizer**

Create `backend/jose/services/error_sanitizer.py`:

```python
import re

_SECRET_QUERY_KEYS = (
    "access_token",
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "auth",
    "key",
    "session",
    "signature",
    "sig",
    "credential",
)

_QUERY_PARAM_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(_SECRET_QUERY_KEYS) + r")=[^&\s\"']+"
)
_AUTH_HEADER_PATTERN = re.compile(r"(?i)(authorization:\s*(?:bearer|basic|token)?\s*)\S+")
_COOKIE_HEADER_PATTERN = re.compile(r"(?i)(cookie:\s*)\S.*")
_USERINFO_URL_PATTERN = re.compile(r"(?i)(https?://)[^\s/@]+@")


def sanitize_error_text(text: str) -> str:
    """Redact common secret shapes from error text before it is persisted.

    Covers secret-looking query-string params, Authorization/Cookie header
    values, and userinfo embedded in URLs. Applied once, at the point an
    error is first recorded, so callers never need to sanitize themselves.
    """
    sanitized = _QUERY_PARAM_PATTERN.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    sanitized = _AUTH_HEADER_PATTERN.sub(r"\1[redacted]", sanitized)
    sanitized = _COOKIE_HEADER_PATTERN.sub(r"\1[redacted]", sanitized)
    sanitized = _USERINFO_URL_PATTERN.sub(r"\1[redacted]@", sanitized)
    return sanitized
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_error_sanitizer.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Ruff check**

Run: `docker compose run --rm api ruff check jose/services/error_sanitizer.py tests/test_error_sanitizer.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/jose/services/error_sanitizer.py backend/tests/test_error_sanitizer.py
git commit -m "feat: add error text sanitizer for secret redaction"
```

---

### Task 3: Wire sanitizer + consecutive_failures into `collect_source`

**Files:**
- Modify: `backend/jose/services/collection.py:1-92`
- Test: `backend/tests/test_collection_service.py`

**Interfaces:**
- Consumes: `sanitize_error_text(text: str) -> str` (Task 2), `Source.consecutive_failures` (Task 1).
- Produces: on a failed `collect_source()` run, `Source.consecutive_failures` increments by 1 and `SourceRun.error_message` / `Source.last_error` are sanitized; on a successful run, `Source.consecutive_failures` resets to `0`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_collection_service.py`, change the import line:

```python
from jose.models import Job
```

to:

```python
from jose.models import Job, SourceRun
```

Then add a failing-collector fixture and three new tests at the end of the file:

```python
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
```

`pytest`, `select`, `_FakeCollector`, and `CollectedJob` are already imported/defined earlier in this file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collection_service.py -v -k "consecutive_failures or sanitizes"`
Expected: FAIL — `consecutive_failures` stays at 0/doesn't exist as expected, or the raw secret is still present in the stored error text.

- [ ] **Step 3: Implement the change**

In `backend/jose/services/collection.py`, add the import at the top:

```python
from jose.collectors.utils import (
    COMPANY_ALIAS_THRESHOLD,
    FUZZY_MATCH_THRESHOLD,
    TITLE_MATCH_THRESHOLD,
    canonicalize_url,
    fuzzy_match_score,
    job_fingerprint,
    material_hash,
    normalize_name,
    normalize_title,
    stable_hash,
)
from jose.config import get_settings
from jose.services.error_sanitizer import sanitize_error_text
```

Then in `collect_source()`, update the success branch (currently lines 70-79):

```python
        run.status = "success"
        run.completed_at = utcnow()
        run.jobs_found = len(result.jobs)
        run.jobs_created = created
        run.jobs_updated = updated
        run.jobs_rejected = result.rejected_count
        source.last_success_at = utcnow()
        source.last_job_count = len(result.jobs)
        source.last_error = None
        source.consecutive_failures = 0
        session.commit()
        return run
```

And the exception branch (currently lines 81-92):

```python
    except Exception as exc:
        session.rollback()
        run = session.get(SourceRun, run.id)
        source = session.get(Source, source_id)
        if run and source:
            error_type = type(exc).__name__
            error_message = sanitize_error_text(str(exc))[:4000]
            run.status = "failed"
            run.completed_at = utcnow()
            run.error_type = error_type
            run.error_message = error_message
            source.last_error = f"{error_type}: {error_message}"[:4000]
            source.consecutive_failures += 1
            session.commit()
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collection_service.py -v`
Expected: PASS (all tests in the file, including the 3 new ones and existing ones)

- [ ] **Step 5: Ruff check and full backend suite**

Run: `make lint` (or `docker compose run --rm api ruff check jose tests`)
Expected: no errors

Run: `make test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/jose/services/collection.py backend/tests/test_collection_service.py
git commit -m "feat: sanitize error text and track consecutive source failures"
```

---

### Task 4: `list_source_runs` service function

**Files:**
- Modify: `backend/jose/services/sources.py`
- Test: `backend/tests/test_sources_service.py`

**Interfaces:**
- Consumes: `get_source(session, user, source_id) -> Source` (existing, same file), `SourceRun` model (`backend/jose/models/core.py`).
- Produces: `list_source_runs(session: Session, user: User, source_id: uuid.UUID, limit: int = 20) -> list[SourceRun]` — consumed by Task 5 (API route).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_sources_service.py`. First, update the imports at the top of the file:

```python
from jose.models import Company, Job, JobSource
```

becomes:

```python
from jose.models import Company, Job, JobSource, SourceRun
```

and:

```python
from jose.services.sources import (
    DeleteConfirmationRequiredError,
    DuplicateSourceUrlError,
    SourceNotFoundError,
    create_source,
    delete_source,
    get_source,
    list_sources,
    update_source,
)
```

becomes:

```python
from jose.services.sources import (
    DeleteConfirmationRequiredError,
    DuplicateSourceUrlError,
    SourceNotFoundError,
    create_source,
    delete_source,
    get_source,
    list_source_runs,
    list_sources,
    update_source,
)
```

Then add these tests at the end of the file:

```python
def test_list_source_runs_orders_newest_first_and_respects_limit(db_session, user):
    from datetime import timedelta

    source = create_source(
        db_session, user, SourceCreate(name="Busy", url="https://busy.example.com/jobs")
    )
    base = utcnow()
    for i in range(25):
        db_session.add(
            SourceRun(
                user_id=user.id,
                source_id=source.id,
                status="success",
                started_at=base + timedelta(seconds=i),
                jobs_found=i,
            )
        )
    db_session.commit()

    runs = list_source_runs(db_session, user, source.id)

    assert len(runs) == 20
    assert runs[0].jobs_found == 24
    assert runs[-1].jobs_found == 5


def test_list_source_runs_raises_for_other_users_source(db_session, user, other_user):
    theirs = create_source(
        db_session, other_user, SourceCreate(name="Theirs", url="https://runs-theirs.example.com")
    )

    with pytest.raises(SourceNotFoundError):
        list_source_runs(db_session, user, theirs.id)
```

`utcnow` is already imported (`from jose.models.base import utcnow`) at the top of this file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_sources_service.py -v -k list_source_runs`
Expected: FAIL — `ImportError: cannot import name 'list_source_runs'`

- [ ] **Step 3: Implement**

In `backend/jose/services/sources.py`, change the model import:

```python
from jose.models import Source, User
```

to:

```python
from jose.models import Source, SourceRun, User
```

Then add this function after `get_source`:

```python
def list_source_runs(
    session: Session, user: User, source_id: uuid.UUID, limit: int = 20
) -> list[SourceRun]:
    get_source(session, user, source_id)
    return list(
        session.scalars(
            select(SourceRun)
            .where(SourceRun.user_id == user.id, SourceRun.source_id == source_id)
            .order_by(SourceRun.started_at.desc())
            .limit(limit)
        ).all()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_sources_service.py -v`
Expected: PASS (full file)

- [ ] **Step 5: Ruff check**

Run: `docker compose run --rm api ruff check jose/services/sources.py tests/test_sources_service.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/jose/services/sources.py backend/tests/test_sources_service.py
git commit -m "feat: add list_source_runs service function"
```

---

### Task 5: `GET /api/v1/sources/{id}/runs` endpoint + `consecutive_failures` on `SourceRead`

**Files:**
- Modify: `backend/jose/schemas.py:69-89` (`SourceRead`), add `SourceRunRead` after it
- Modify: `backend/jose/api/routes/sources.py`
- Test: `backend/tests/test_sources_api.py`

**Interfaces:**
- Consumes: `list_source_runs` (Task 4), `SourceNotFoundError` (existing, `jose/services/sources.py`).
- Produces: `SourceRunRead` Pydantic schema, `SourceRead.consecutive_failures: int` — both consumed by the frontend (Task 6).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_sources_api.py`, at the end of the file:

```python
def test_source_read_includes_consecutive_failures(client, db_session):
    created = _create(client, url="https://api-consecutive.example.com")
    try:
        assert created["consecutive_failures"] == 0
    finally:
        _cleanup(db_session, created["id"])


def test_list_source_runs_empty(client, db_session):
    created = _create(client, url="https://api-runs-empty.example.com")
    try:
        response = client.get(f"/api/v1/sources/{created['id']}/runs")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        _cleanup(db_session, created["id"])


def test_list_source_runs_returns_newest_first_and_respects_limit(client, db_session):
    from datetime import timedelta

    from jose.models import Source, SourceRun
    from jose.models.base import utcnow

    created = _create(client, url="https://api-runs-order.example.com")
    try:
        source = db_session.get(Source, uuid.UUID(created["id"]))
        base = utcnow()
        for i in range(25):
            db_session.add(
                SourceRun(
                    user_id=source.user_id,
                    source_id=source.id,
                    status="success",
                    started_at=base + timedelta(seconds=i),
                    jobs_found=i,
                )
            )
        db_session.commit()

        response = client.get(f"/api/v1/sources/{created['id']}/runs")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 20
        assert body[0]["jobs_found"] == 24
    finally:
        _cleanup(db_session, created["id"])


def test_list_source_runs_unknown_source_returns_404(client):
    response = client.get(f"/api/v1/sources/{uuid.uuid4()}/runs")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_sources_api.py -v -k "consecutive_failures or list_source_runs"`
Expected: FAIL — `consecutive_failures` missing from the response body, and `/runs` returns 404 (route not found) or 422.

- [ ] **Step 3: Implement the schema changes**

In `backend/jose/schemas.py`, add one field to `SourceRead` (after `detected_at` on line 88):

```python
    detected_at: datetime | None
    consecutive_failures: int
```

Then add a new schema directly after the `SourceRead` class (before `JobRead`):

```python
class SourceRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    jobs_found: int
    jobs_created: int
    jobs_updated: int
    jobs_rejected: int
    error_type: str | None
    error_message: str | None
```

- [ ] **Step 4: Implement the route**

In `backend/jose/api/routes/sources.py`, change the model import:

```python
from jose.models import Source
```

to:

```python
from jose.models import Source, SourceRun
```

and the schema import:

```python
from jose.schemas import QueueResponse, SourceCreate, SourceRead, SourceUpdate
```

to:

```python
from jose.schemas import QueueResponse, SourceCreate, SourceRead, SourceRunRead, SourceUpdate
```

Then add this route after `get_source` (after line 32, before `update_source`):

```python
@router.get("/{source_id}/runs", response_model=list[SourceRunRead])
def list_source_runs(
    source_id: uuid.UUID,
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=20),
) -> list[SourceRun]:
    try:
        return sources_service.list_source_runs(db, user, source_id, limit=limit)
    except sources_service.SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc
```

`Query` is already imported at the top of this file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_sources_api.py -v`
Expected: PASS (full file)

- [ ] **Step 6: Ruff check and full backend suite**

Run: `make lint`
Expected: no errors

Run: `make test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/jose/schemas.py backend/jose/api/routes/sources.py backend/tests/test_sources_api.py
git commit -m "feat: add GET /sources/{id}/runs endpoint and expose consecutive_failures"
```

---

### Task 6: Frontend API client additions

**Files:**
- Modify: `web/lib/api.ts`

**Interfaces:**
- Consumes: `GET /api/v1/sources/{id}` (existing), `GET /api/v1/sources/{id}/runs` (Task 5).
- Produces: `SourceRun` type, `getSource(id: string): Promise<Source>`, `getSourceRuns(id: string): Promise<SourceRun[]>`, `Source.consecutive_failures: number` — consumed by Tasks 7-9.

- [ ] **Step 1: Add `consecutive_failures` to the `Source` type**

In `web/lib/api.ts`, update the `Source` type:

```typescript
export type Source = {
  id: string;
  name: string;
  url: string;
  category: string;
  portfolio_firm: string | null;
  adapter: string;
  enabled: boolean;
  priority: number;
  collection_frequency: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_job_count: number | null;
  last_error: string | null;
  consecutive_failures: number;
};
```

- [ ] **Step 2: Add the `SourceRun` type**

Add after the `Source` type:

```typescript
export type SourceRun = {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  jobs_found: number;
  jobs_created: number;
  jobs_updated: number;
  jobs_rejected: number;
  error_type: string | null;
  error_message: string | null;
};
```

- [ ] **Step 3: Add the fetch functions**

Add after `getSources`:

```typescript
export async function getSource(id: string): Promise<Source> {
  return getJson<Source>(`/api/v1/sources/${id}`);
}

export async function getSourceRuns(id: string): Promise<SourceRun[]> {
  return getJson<SourceRun[]>(`/api/v1/sources/${id}/runs`);
}
```

- [ ] **Step 4: Verify the frontend still builds**

Run: `docker compose run --rm web npm run lint`
Expected: no errors (existing `Source` consumers — `source-manager.tsx`, `web/app/page.tsx` — don't construct `Source` objects by hand, they only read fields, so the new required field doesn't break them; TypeScript would flag it here if it did).

- [ ] **Step 5: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat: add SourceRun type and source detail fetch helpers"
```

---

### Task 7: `SourceRunHistory` component

**Files:**
- Create: `web/components/source-run-history.tsx`

**Interfaces:**
- Consumes: `SourceRun` type (Task 6).
- Produces: `SourceRunHistory({ runs }: { runs: SourceRun[] })` — consumed by Task 8 (detail page).

- [ ] **Step 1: Write the component**

Create `web/components/source-run-history.tsx`:

```tsx
import type { SourceRun } from "@/lib/api";

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

function formatDuration(run: SourceRun): string {
  if (!run.completed_at) return "—";
  const seconds = Math.max(
    0,
    Math.round(
      (new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000,
    ),
  );
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function RunStatus({ run }: { run: SourceRun }) {
  if (run.status === "failed") return <span className="status bad">Failed</span>;
  if (run.status === "running") return <span className="status neutral">Running</span>;
  if (run.jobs_found === 0) return <span className="status neutral">Success · 0 jobs</span>;
  return <span className="status good">Success</span>;
}

export function SourceRunHistory({ runs }: { runs: SourceRun[] }) {
  if (runs.length === 0) {
    return (
      <p className="emptyState">
        No runs recorded yet. Trigger a collection to see history here.
      </p>
    );
  }

  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Started</th>
            <th>Duration</th>
            <th>Found</th>
            <th>Created</th>
            <th>Updated</th>
            <th>Rejected</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>
                <RunStatus run={run} />
              </td>
              <td>{formatDateTime(run.started_at)}</td>
              <td>{formatDuration(run)}</td>
              <td>{run.jobs_found}</td>
              <td>{run.jobs_created}</td>
              <td>{run.jobs_updated}</td>
              <td>{run.jobs_rejected}</td>
              <td>
                {run.error_message ? (
                  <span title={run.error_message}>{run.error_type ?? "Error"}</span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Lint check**

Run: `docker compose run --rm web npm run lint`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add web/components/source-run-history.tsx
git commit -m "feat: add SourceRunHistory table component"
```

---

### Task 8: Source detail page

**Files:**
- Create: `web/app/sources/[id]/page.tsx`
- Modify: `web/app/globals.css` (add `.kvGrid`, `.warningBanner` styles)

**Interfaces:**
- Consumes: `getSource`, `getSourceRuns` (Task 6), `SourceRunHistory` (Task 7), `CollectButton` (existing, `web/components/collect-button.tsx`).

- [ ] **Step 1: Add the new CSS classes**

In `web/app/globals.css`, add after the existing `.formError` rule (the last rule in the file, currently line 169):

```css
.warningBanner { margin: 0 0 1rem; padding: .8rem 1rem; border-radius: .6rem; color: var(--amber); background: #fff8e7; font-weight: 700; }

.kvGrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .9rem; margin-bottom: 1.5rem; }
.kvGrid .kvItem { padding: 1rem 1.2rem; border: 1px solid var(--line); border-radius: .8rem; background: var(--panel); }
.kvGrid .kvItem.warning { border-color: var(--amber); background: #fff8e7; }
.kvGrid dt { margin: 0; color: var(--muted); font-size: .74rem; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }
.kvGrid dd { margin: .4rem 0 0; font-weight: 700; word-break: break-word; }

.status.warn { color: var(--amber); background: #fff8e7; }
```

- [ ] **Step 2: Write the page**

Create `web/app/sources/[id]/page.tsx`:

```tsx
import Link from "next/link";
import { CollectButton } from "@/components/collect-button";
import { SourceRunHistory } from "@/components/source-run-history";
import { getSource, getSourceRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

export default async function SourceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  try {
    const [source, runs] = await Promise.all([getSource(id), getSourceRuns(id)]);
    const lastRun = runs[0] ?? null;
    const lastRunDuration =
      lastRun && lastRun.completed_at
        ? `${Math.max(
            0,
            Math.round(
              (new Date(lastRun.completed_at).getTime() -
                new Date(lastRun.started_at).getTime()) /
                1000,
            ),
          )}s`
        : "—";

    return (
      <section>
        <div className="pageHeader">
          <div>
            <p className="eyebrow">{source.category.replaceAll("_", " ")}</p>
            <h1>{source.name}</h1>
            <p>
              <a href={source.url} rel="noreferrer" target="_blank">
                {source.url}
              </a>
            </p>
          </div>
          <div className="rowActions">
            {source.enabled ? <CollectButton sourceId={source.id} /> : null}
            <Link className="ghostButton" href="/sources">
              Back to sources
            </Link>
          </div>
        </div>

        {source.consecutive_failures >= 2 ? (
          <p className="warningBanner">
            {source.consecutive_failures} failed runs in a row. Check the adapter or URL below.
          </p>
        ) : null}

        <dl className="kvGrid">
          <div className="kvItem">
            <dt>Last attempt</dt>
            <dd>{formatDate(source.last_attempt_at)}</dd>
          </div>
          <div className="kvItem">
            <dt>Last success</dt>
            <dd>{formatDate(source.last_success_at)}</dd>
          </div>
          <div className="kvItem">
            <dt>Last run duration</dt>
            <dd>{lastRunDuration}</dd>
          </div>
          <div className="kvItem">
            <dt>Last job count</dt>
            <dd>{source.last_job_count ?? "—"}</dd>
          </div>
          <div className="kvItem">
            <dt>Adapter</dt>
            <dd>
              <code>{source.adapter}</code>
            </dd>
          </div>
          <div className={`kvItem${source.last_error ? " warning" : ""}`}>
            <dt>Current error</dt>
            <dd>{source.last_error ?? "None"}</dd>
          </div>
        </dl>

        <div className="panel">
          <div className="panelHeader">
            <h2>Run history</h2>
            <span className="countPill">{runs.length} recent runs</span>
          </div>
          <SourceRunHistory runs={runs} />
        </div>
      </section>
    );
  } catch (error) {
    return (
      <section className="panel apiError">
        <p className="eyebrow">Source unavailable</p>
        <h1>This source could not be loaded.</h1>
        <p>
          It may not exist, or the JOSE API may be unreachable. <Link href="/sources">Back to sources</Link>.
        </p>
        <pre>{error instanceof Error ? error.message : "Unknown error"}</pre>
      </section>
    );
  }
}
```

- [ ] **Step 3: Lint and build check**

Run: `docker compose run --rm web npm run lint`
Expected: no errors

Run: `docker compose run --rm -v /app/.next web npm run build`
Expected: build succeeds, `/sources/[id]` listed as a dynamic route.

- [ ] **Step 4: Commit**

```bash
git add web/app/sources/[id]/page.tsx web/app/globals.css
git commit -m "feat: add source detail page with health summary and run history"
```

---

### Task 9: Link the sources list to the detail page and flag repeated failures

**Files:**
- Modify: `web/components/source-manager.tsx`

**Interfaces:**
- Consumes: `Source.consecutive_failures` (Task 6), `/sources/[id]` route (Task 8).

- [ ] **Step 1: Import `Link`**

In `web/components/source-manager.tsx`, add to the top imports:

```tsx
import Link from "next/link";
```

- [ ] **Step 2: Make the source name link to its detail page**

Replace the name cell (currently):

```tsx
                  <td>
                    <a href={source.url} rel="noreferrer" target="_blank">
                      {source.name}
                    </a>
                    <small>{source.url}</small>
                  </td>
```

with:

```tsx
                  <td>
                    <Link href={`/sources/${source.id}`}>{source.name}</Link>
                    <small>
                      <a href={source.url} rel="noreferrer" target="_blank">
                        {source.url}
                      </a>
                    </small>
                  </td>
```

- [ ] **Step 3: Add the repeated-failures badge**

Replace the status cell (currently):

```tsx
                  <td>
                    {source.last_error ? (
                      <span className="status bad" title={source.last_error}>
                        Failed
                      </span>
                    ) : source.enabled ? (
                      <span className="status good">Enabled</span>
                    ) : (
                      <span className="status neutral">Disabled</span>
                    )}
                  </td>
```

with:

```tsx
                  <td>
                    <span className="rowActions">
                      {source.last_error ? (
                        <span className="status bad" title={source.last_error}>
                          Failed
                        </span>
                      ) : source.enabled ? (
                        <span className="status good">Enabled</span>
                      ) : (
                        <span className="status neutral">Disabled</span>
                      )}
                      {source.consecutive_failures >= 2 ? (
                        <span
                          className="status warn"
                          title={`${source.consecutive_failures} failed runs in a row`}
                        >
                          Repeated failures
                        </span>
                      ) : null}
                    </span>
                  </td>
```

- [ ] **Step 4: Lint and build check**

Run: `docker compose run --rm web npm run lint`
Expected: no errors

Run: `docker compose run --rm -v /app/.next web npm run build`
Expected: build succeeds

- [ ] **Step 5: Commit**

```bash
git add web/components/source-manager.tsx
git commit -m "feat: link sources list to detail page and flag repeated failures"
```

---

### Task 10: Manual verification in the browser

**Files:** none (verification only)

- [ ] **Step 1: Start the stack**

Run: `make dev` (uses Colima-backed Docker per this machine's setup)
Expected: PostgreSQL, API, worker, and web start without errors.

- [ ] **Step 2: Exercise the golden path**

In a browser:
1. Go to `http://localhost:3000/sources`, confirm existing sources still list correctly and each name links to `/sources/<id>`.
2. Open a source's detail page. Confirm it shows category, URL, last attempt/success, last run duration, last job count, adapter, current error (or "None"), and a run-history table.
3. Click "Collect" on an enabled source's detail page; confirm it queues (button shows "Queued").
4. Trigger the worker (or wait for it) to process the queued task, then reload the detail page — confirm a new row appears in run history with the correct status (Success, or Success · 0 jobs if nothing was found, or Failed).

- [ ] **Step 3: Exercise the repeated-failure and zero-result edge cases**

1. Point a source at an unreachable/invalid URL (e.g. edit an existing source's URL to something that will 404) and trigger collection twice in a row.
2. On `/sources`, confirm the "Repeated failures" badge appears next to that source's status pill.
3. Open its detail page — confirm the amber warning banner appears above the health grid, and both failed runs show red "Failed" status with the (sanitized) error visible.
4. Restore the source's URL to something valid that returns zero jobs (or check an existing source with `last_job_count: 0`), trigger a collection, and confirm the resulting run history row reads "Success · 0 jobs" in neutral styling — not red/Failed.

- [ ] **Step 4: Report results**

No commit for this task — report back whether all checks passed, and any UI issues observed (do not silently fix cosmetic issues without noting them — file them as follow-ups if out of scope for this plan).

---

## Definition of Done

- All 6 acceptance criteria from Issue 10 are met (verified in Task 10).
- `make lint` passes (ruff + eslint).
- `make test` passes (full backend suite including new tests).
- `make build` passes (frontend build succeeds).
- Migration `0008_source_health_dashboard` is applied and reversible.
- No unsanitized secret-shaped text can reach `SourceRun.error_message` or `Source.last_error` (covered by Task 2/3 tests).
