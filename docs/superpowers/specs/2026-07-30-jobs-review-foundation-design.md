# Jobs Review Foundation (Issue 11)

## Goal

Give the user a useful pre-scoring workspace over collected jobs: search and
filter the list, open a job to see its full description, source lineage, and
version history, and record a decision (already applied, irrelevant, watch,
archived) on each one. No AI involved — this is a manual review surface over
data that mostly already exists from Issues 04–08.

## Acceptance criteria (from `docs/backlog/PHASE_0_1_BACKLOG.md`)

- Search and filters for company, title, source, date, location, ATS, and status.
- Job detail page shows description, source lineage, and version history.
- User can mark already applied, irrelevant, watch, or archived.
- Decisions are user-scoped and audited.
- No AI is required for this issue.

## Existing foundation

Most of the data already exists:

- `Job` (`backend/jose/models/core.py`) already carries `description_text`,
  `description_html`, `location`, `ats_type`, `published_at`, `status`
  (`active`/`removed`/`merged` — lifecycle, not user intent).
- `JobSource` already links a job to every `Source` that lists it
  (`source_job_url`, `is_active`, `first_seen_at`/`last_seen_at`) — this is
  the source lineage for the detail page.
- `JobVersion` already stores one row per distinct `content_hash` seen, with
  `is_material` distinguishing real changes from formatting noise — this is
  the version history for the detail page.
- `SystemEvent` (generic audit log) is already used by
  `backend/jose/services/job_merge.py` for `job_merged`/`job_unmerged` events
  — the same mechanism this issue reuses for decision audit trail.
- `GET /api/v1/jobs` and `web/app/jobs/page.tsx` already exist but are
  minimal: no filters, no pagination, no detail page, no decision field.

What's missing: a decision field + audit trail, server-side search/filtering
(the first list in this repo whose filters need to run in SQL rather than
in-memory), a job detail endpoint/page, and decision controls in the UI.

## Backend changes

### 1. `Job.user_decision` (new column)

- `Job.user_decision: Mapped[str | None] = mapped_column(String(20))` —
  nullable; `None` means no decision has been made yet. Plain string column,
  matching how `Job.status` and other model-layer string fields work today
  — the `JobDecision` enum (values: `applied`, `irrelevant`, `watch`,
  `archived`) lives only in `schemas.py`, consistent with how
  `SourceCategory`/`SourceAdapter`/`JobMergeAction` are enums at the API
  boundary but plain strings on the model.
- New index `Index("ix_jobs_user_decision", "user_id", "user_decision")`.
- Chosen over a separate decision-history table (discussed and rejected):
  the column mirrors how `Job.status` already works, and `SystemEvent`
  already gives us an audit trail without a second source of truth for
  "what is the decision right now."

Requires an Alembic migration: `backend/alembic/versions/0009_job_decisions.py`.

### 2. `services/jobs.py` (new file)

Two functions, following `job_merge.py`'s lookup → validate → mutate →
audit → commit shape:

- `list_jobs(session, user, filters, limit, offset) -> list[JobWithCompany]`
  — builds the `SELECT` from `GET /api/v1/jobs`'s query params (see below).
- `get_job_detail(session, user, job_id) -> JobDetail` — loads the job
  (raising `JobNotFoundError` if missing or not owned by `user`, translated
  to 404 by the route), plus its `JobSource` rows joined with `Source`
  (name, category), plus its `JobVersion` rows ordered `seen_at` descending.
- `set_job_decision(session, user, job_id, decision: str | None) -> Job` —
  looks up the job scoped to `user_id` (404 via `JobNotFoundError`),
  captures the previous value, sets `user_decision`, appends a
  `SystemEvent(event_type="job_decision_set", entity_type="job",
  entity_id=job.id, message=..., data={"previous": prev, "decision":
  decision})`, commits, refreshes, returns the job. Setting the same
  decision again still writes an audit row (explicit re-confirmation is
  worth recording) but is not treated as an error.

### 3. `GET /api/v1/jobs` — extended with query params

All optional; combined with `AND`. Reuses the existing `Job.user_id ==
user.id, Job.status != "merged"` base filter.

| param | maps to | behavior |
|---|---|---|
| `company` | `Company.name` | case-insensitive substring (`ILIKE`) |
| `title` | `Job.title` | case-insensitive substring (`ILIKE`) |
| `source_id` | `JobSource.source_id` | exact match, joins `JobSource` |
| `date_from` / `date_to` | `Job.first_seen_at` | inclusive range |
| `location` | `Job.location` | case-insensitive substring (`ILIKE`) |
| `ats_type` | `Job.ats_type` | exact match |
| `status` | `Job.status` | exact match (`active`/`removed`); default: no restriction beyond the existing `!= "merged"` |
| `decision` | `Job.user_decision` | repeatable (`?decision=applied&decision=watch`); **default when omitted**: excludes `irrelevant` and `archived` so the default view stays focused on jobs still needing attention; pass explicitly to see them |
| `limit` | — | default 50, max 200 |
| `offset` | — | default 0 |

Response gains `user_decision` on each row's dict; `JobRead` schema gains
`user_decision: str | None`.

### 4. `GET /api/v1/jobs/{job_id}` (new)

Returns a `JobDetailRead`: all `JobRead` fields plus `description_text`,
`description_html`, `department`, `remote_type`, `employment_type`,
`compensation_min`/`max`, `currency`, `canonical_url`, `company_name`,
`sources: list[JobSourceRead]` (source name, category, `source_job_url`,
`is_active`, `first_seen_at`, `last_seen_at`), `versions:
list[JobVersionRead]` (`seen_at`, `is_material`, `content_hash`). 404 via
`JobNotFoundError` for missing/foreign jobs, same pattern as `sources.py`.

### 5. `PATCH /api/v1/jobs/{job_id}/decision` (new)

Body: `{"decision": "applied" | "irrelevant" | "watch" | "archived" | null}`
(`null` clears it). Returns the updated `JobRead`. 404 for missing/foreign
job; 422 for an invalid decision value (enum validation via Pydantic).

### 6. Schema changes (`backend/jose/schemas.py`)

```python
class JobDecision(StrEnum):
    APPLIED = "applied"
    IRRELEVANT = "irrelevant"
    WATCH = "watch"
    ARCHIVED = "archived"

class JobDecisionUpdate(BaseModel):
    decision: JobDecision | None

class JobSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_id: uuid.UUID
    source_name: str
    source_category: str
    source_job_url: str | None
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime

class JobVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seen_at: datetime
    is_material: bool
    content_hash: str

class JobDetailRead(JobRead):
    description_text: str | None
    description_html: str | None
    department: str | None
    remote_type: str | None
    employment_type: str | None
    compensation_min: int | None
    compensation_max: int | None
    currency: str | None
    canonical_url: str
    company_name: str
    sources: list[JobSourceRead]
    versions: list[JobVersionRead]
```

`JobRead` gains `user_decision: str | None` and `company_name: str`.

## Frontend changes

### 1. `web/lib/api.ts`

- `Job` type gains `user_decision: string | null` and `company_name`.
- New `JobDetail`, `JobSourceLineage`, `JobVersionEntry` types mirroring the
  new backend schemas.
- `getJobs()` becomes `getJobs(params: JobFilters): Promise<Job[]>`, builds
  a query string from the filter object, `cache: "no-store"` as today.
- New `getJob(id: string): Promise<JobDetail>`.
- New client-side mutator in `browser-api.ts` usage:
  `setJobDecision(id: string, decision: string | null)` → `PATCH
  /api/v1/jobs/{id}/decision`.

### 2. `web/app/jobs/page.tsx` — reworked

Stays a server component. Reads filters from `searchParams` (Next.js App
Router convention — keeps filters shareable/bookmarkable and makes
pagination trivial via `?offset=`), calls `getJobs(filters)`, renders:

- `job-filters.tsx` (new, `"use client"`) — search/select inputs for
  company, title, source, date range, location, ATS, status, decision.
  Same visual conventions as `source-manager.tsx`'s filter row. On change,
  pushes new `searchParams` via `useRouter().push` (server refetch, not
  client-side filtering — this is the one list in the repo where filtering
  now happens server-side, called out explicitly since it's a new pattern).
- Job list: each row/card shows company, title, location, ATS badge, source
  count, first seen date, and a `job-decision-controls.tsx` (new,
  `"use client"`) — a small set of buttons/dropdown (Applied / Irrelevant /
  Watch / Archived / clear) that calls `setJobDecision` with per-row busy
  state, matching `job-merge-review.tsx`'s existing optimistic-update style.
- Row title links to `/jobs/${job.id}`.
- "`N` of `M`" count pill + Prev/Next (offset-based) pagination controls.

### 3. `web/app/jobs/[id]/page.tsx` (new)

Server component, same pattern as `sources/[id]/page.tsx`: fetch in
try/catch, render `apiError` panel on 404/failure. Sections:

- Header: title, company, location, ATS badge, link to original posting,
  `job-decision-controls.tsx` (same component as the list, reused).
- Description (renders `description_text` only, in a `<pre>`-style block;
  `description_html` is deliberately never rendered as HTML since it comes
  from external, uncontrolled sources and this repo has no HTML sanitizer,
  which would make `dangerouslySetInnerHTML` a stored-XSS vector).
- Source lineage table: source name/category, link/URL, active/inactive,
  first/last seen — reuses the table styling from `source-run-history.tsx`.
- Version history table: seen date, material/formatting badge — same table
  styling.

## Testing plan

Backend (pytest, real Postgres per existing `conftest.py` fixtures), new
`test_jobs_service.py` and extended `test_jobs_api.py`:

- `list_jobs`: each filter param in isolation and combined; default
  `decision` filter excludes irrelevant/archived; explicit `decision`
  params include them; pagination (`limit`/`offset`) correctness;
  cross-user isolation.
- `get_job_detail`: returns sources and versions correctly ordered; 404 for
  missing/foreign job.
- `set_job_decision`: sets each decision value; clears with `null`; writes
  exactly one `SystemEvent` per change with correct `previous`/`decision`
  in `data`; re-setting the same decision still writes an audit row; 404
  for missing/foreign job (`..._rejects_other_user` test, matching the
  `job_merge` precedent); 422 for an invalid decision string.

Frontend: no test runner in this repo (per existing convention). Verify
with `npm run lint` and `npm run build`, plus a manual pass in the browser
against the running dev stack — apply each filter individually and in
combination, open a job detail page, set and clear each decision from both
the list and detail page, confirm irrelevant/archived jobs disappear from
the default list and reappear when explicitly filtered for.

## Definition of done

- All acceptance criteria above are met.
- Migration `0009_job_decisions` added and applied.
- Ruff passes.
- `npm run lint` and `npm run build` pass.
- New backend tests pass alongside the existing suite.
- No business logic in route handlers — routes call `services/jobs.py` only.
- Every decision change produces a `SystemEvent` audit row.
