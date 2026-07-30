# Source Health Dashboard (Issue 10)

## Goal

Make source failures actionable. A user looking at a source should be able to
tell, at a glance, whether it's healthy, what happened on its last run, and
whether it's stuck in a repeated-failure state — without reading logs.

## Acceptance criteria (from `docs/backlog/PHASE_0_1_BACKLOG.md`)

- Source page shows last attempt, last success, duration, counts, adapter, and error.
- User can rerun one source.
- User can inspect recent run history.
- Repeated failures are highlighted.
- A zero-result successful run is distinguishable from failure.
- Error text is sanitized for secrets.

## Existing foundation

Most of the data already exists:

- `Source` (backend/jose/models/core.py) already carries `last_attempt_at`,
  `last_success_at`, `last_job_count`, `last_error`, `adapter`.
- `SourceRun` already carries `status`, `started_at`, `completed_at`,
  `jobs_found/created/updated/rejected`, `error_type`, `error_message`.
- `POST /api/v1/sources/{id}/collect` already exists and enqueues a rerun
  (`CollectButton` component already calls it).

What's missing: a way to list a source's run history, a way to flag repeated
failures without an expensive per-render computation, sanitization of error
text before it's ever persisted, and a UI surface for all of this.

## Backend changes

### 1. `Source.consecutive_failures` (new column)

Persisted counter on `Source`, `Integer`, `default=0`, `nullable=False`.

- `collect_source()` (backend/jose/services/collection.py) sets it to `0` on
  a successful run and increments it by 1 on a failed run — in the same
  places that already update `last_success_at` / `last_error`.
- Chosen over computing from `SourceRun` history at read time because it's
  read on every sources-list render; a persisted counter avoids an N+1 query
  per source and matches the existing convenience-field pattern already used
  for `last_error` / `last_job_count`.

Requires an Alembic migration: `backend/alembic/versions/0008_source_consecutive_failures.py`.

"Repeated failures" threshold: **2 or more** consecutive failures.

### 2. Error sanitization

New module `backend/jose/services/error_sanitizer.py` exporting
`sanitize_error_text(text: str) -> str`.

Redacts, case-insensitively:

- Query-string parameters whose key looks secret-shaped (`token`, `api_key`,
  `apikey`, `key`, `secret`, `password`, `passwd`, `pwd`, `auth`,
  `access_token`, `session`, `sig`, `signature`, `credential`) — value
  replaced with `[redacted]`, key kept.
- `Authorization: <scheme> <value>` header text (e.g. `Bearer …`, `Basic …`)
  — value replaced with `[redacted]`.
- `Cookie: ...` header text — value replaced with `[redacted]`.
- Userinfo in URLs (`https://user:pass@host/...`) — replaced with
  `https://[redacted]@host/...`.

Applied once, inside `collect_source()`'s exception handler, before the
message is written to `SourceRun.error_message` or `Source.last_error`. This
covers all current and future collectors without collectors needing to know
about it. Truncation to 4000 chars stays as-is, applied after sanitization.

### 3. `GET /api/v1/sources/{source_id}/runs`

New route in `backend/jose/api/routes/sources.py`.

- Query param `limit`, default 20, capped at 20 (no pagination in this
  phase — matches the approved design; fixed window is enough at current
  run volumes).
- Returns `list[SourceRunRead]`, ordered `started_at` descending.
- 404 (`SourceNotFoundError`) if the source doesn't exist or isn't owned by
  the current user — identical ownership check to the other source routes.
- New service function `list_source_runs(session, user, source_id, limit)`
  in `backend/jose/services/sources.py`, reusing `get_source()` for the
  ownership check before querying `SourceRun`.

### 4. Schema changes (`backend/jose/schemas.py`)

- `SourceRead` gains `consecutive_failures: int`.
- New `SourceRunRead`:
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
  Duration is derived client-side from `started_at`/`completed_at` rather
  than duplicated as a backend field.

## Frontend changes

### 1. `web/lib/api.ts`

- `Source` type gains `consecutive_failures: number`.
- New `SourceRun` type mirroring `SourceRunRead`.
- New `getSource(id: string): Promise<Source>` and
  `getSourceRuns(id: string): Promise<SourceRun[]>`.

### 2. `web/app/sources/[id]/page.tsx` (new)

Server component, same pattern as `web/app/sources/page.tsx`:

- Fetches the source and its run history in parallel.
- Header: name, URL, category, adapter, frequency, enabled/disabled.
- Health summary: last attempt, last success, last run duration (from the
  most recent run in history), last job count, current error (if any,
  sanitized text already, shown in full — not just as a tooltip).
- "Repeated failures" warning banner when `consecutive_failures >= 2`,
  stating the count.
- Rerun action: reuses the existing `CollectButton` component.
- Run history table (up to 20 rows): status, started at, duration,
  found/created/updated/rejected, error. Status rendering:
  - `success` with `jobs_found > 0` → green "Success".
  - `success` with `jobs_found === 0` → neutral "Success · 0 jobs" (never
    rendered as an error/warning state — this is the zero-result-success
    distinction from failure).
  - `failed` → red "Failed", error text shown/expandable.
  - `running` → neutral "Running".

### 3. `web/components/source-manager.tsx`

- Source name in the table becomes a `Link` to `/sources/${source.id}`.
- A "Repeated failures" badge renders next to the existing status pill when
  `consecutive_failures >= 2` (additive — doesn't replace the existing
  Failed/Enabled/Disabled status logic, which is based on `last_error`).

## Testing plan

Backend (pytest, real Postgres per existing `conftest.py` fixtures):

- `error_sanitizer`: redaction of query-string secrets, Authorization
  headers, Cookie headers, userinfo URLs; non-secret text passes through
  unchanged.
- `collect_source`: `consecutive_failures` increments across repeated
  failures and resets to 0 on the next success; stored error text is
  sanitized (extend `test_collection_service.py`).
- `list_source_runs` / `GET /{id}/runs`: ordering (newest first), limit
  enforcement, 404 for unknown/foreign source, cross-user isolation
  (extend `test_sources_api.py` and/or `test_sources_service.py`).

Frontend: no test runner in this repo. Verify with `npm run lint` and
`npm run build`, and a manual pass in the browser against the running dev
stack (create a source, trigger a failure and a success, confirm the badge,
banner, and run-history rendering).

## Definition of done

- All acceptance criteria above are met.
- Migration `0008_source_consecutive_failures` added and applied.
- Ruff passes.
- `npm run lint` and `npm run build` pass.
- New backend tests pass alongside the existing suite.
- No secrets ever land in `SourceRun.error_message` / `Source.last_error`
  for the redaction patterns covered above.
