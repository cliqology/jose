# Jobs Review Foundation (Issue 11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a jobs review workspace: server-side search/filters (company, title, source, date, location, ATS, status), a job detail page (description, source lineage, version history), and a per-user decision (applied/irrelevant/watch/archived) that's audited and hidden from the default list when it's irrelevant/archived.

**Architecture:** Additive changes over the existing Job/JobSource/JobVersion/SystemEvent tables from Issues 07–08. One new nullable `Job.user_decision` column plus `SystemEvent` audit rows (no new table). A new `backend/jose/services/jobs.py` owns all query/filter/audit logic (routes stay thin, matching `services/job_merge.py`'s shape). Three job routes: extended `GET /api/v1/jobs`, new `GET /api/v1/jobs/{id}`, new `PATCH /api/v1/jobs/{id}/decision`. Frontend reworks `jobs/page.tsx` into a searchParams-driven server component + new client components (`job-filters.tsx`, `jobs-table.tsx`, `job-decision-controls.tsx`), and adds `jobs/[id]/page.tsx`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (ORM), Alembic, Pydantic v2, pytest (real Postgres per `conftest.py`), Next.js 15 App Router, TypeScript.

## Global Constraints

- Every user-owned record includes `user_id`; every service query filters by `Job.user_id == user.id` (or the equivalent join). [CLAUDE.md]
- Use timezone-aware UTC datetimes everywhere — never compare a naive `datetime` against `Job.first_seen_at` (a `DateTime(timezone=True)` column). [CLAUDE.md]
- Use typed Pydantic schemas at API boundaries; do not put business logic in route handlers — routes call `services/jobs.py` only. [CLAUDE.md]
- Every persisted schema change ships an Alembic migration with a full `upgrade()`/`downgrade()`. [CLAUDE.md]
- Unit tests never make live network calls; this plan's tests all run against the real Postgres test database per `backend/tests/conftest.py` fixtures. [CLAUDE.md]
- No AI is used anywhere in this feature. [Issue 11 acceptance criteria]
- Every job-decision change must produce exactly one `SystemEvent` audit row. [spec: `docs/superpowers/specs/2026-07-30-jobs-review-foundation-design.md`]
- Never render collected `description_html` as raw HTML in the browser (`dangerouslySetInnerHTML`) — job descriptions come from external, uncontrolled sources and this repo has no HTML sanitizer installed. Render `description_text` (plain text) only. This is a deliberate deviation introduced during planning, not present in the committed spec — flagged here because it's a security-relevant decision.
- `backend/jose/schemas.py`'s existing `JobRead` class is currently unused by any route (verified: `grep -rn "JobRead" backend/jose/ backend/tests/` only matches its own definition). Do not extend it for this feature — introduce new, purpose-built schemas (`JobDetailRead`, `JobDecisionRead`, etc.) instead of adding fields to dead code. This is a deliberate deviation from the literal spec text ("JobRead gains user_decision and company_name"), made because the spec was written before this was discovered.

---

### Task 1: `Job.user_decision` column + migration

**Files:**
- Modify: `backend/jose/models/core.py:108-150` (the `Job` class)
- Create: `backend/alembic/versions/0009_job_decisions.py`

**Interfaces:**
- Produces: `Job.user_decision: str | None` — nullable column, no ORM-level enum (matches how `Job.status` is a plain string). Values used elsewhere in this plan: `"applied"`, `"irrelevant"`, `"watch"`, `"archived"`, or `None`.

- [ ] **Step 1: Add the column and index to the model**

In `backend/jose/models/core.py`, inside the `Job` class, add `user_decision` after `status` and add an index to `__table_args__`:

```python
class Job(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_jobs_user_fingerprint"),
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_user_first_seen", "user_id", "first_seen_at"),
        Index("ix_jobs_user_decision", "user_id", "user_decision"),
    )
    ...
    status: Mapped[str] = mapped_column(String(50), default="active")
    user_decision: Mapped[str | None] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(64))
```

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/0009_job_decisions.py`:

```python
"""Add user_decision to jobs.

Revision ID: 0009_job_decisions
Revises: 0008_source_health_dashboard
Create Date: 2026-07-30
"""

from alembic import op  # noqa: I001
import sqlalchemy as sa

revision = "0009_job_decisions"
down_revision = "0008_source_health_dashboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("user_decision", sa.String(length=20), nullable=True))
    op.create_index(
        "ix_jobs_user_decision", "jobs", ["user_id", "user_decision"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_user_decision", table_name="jobs")
    op.drop_column("jobs", "user_decision")
```

- [ ] **Step 3: Apply the migration and confirm no regressions**

Run: `make migrate`
Expected: migration `0009_job_decisions` applies cleanly (no errors).

Run: `make test`
Expected: full existing suite still passes (this is a pure additive nullable column — nothing should break).

- [ ] **Step 4: Commit**

```bash
git add backend/jose/models/core.py backend/alembic/versions/0009_job_decisions.py
git commit -m "feat: add Job.user_decision column for jobs review decisions"
```

---

### Task 2: Pydantic schemas for job decisions and detail view

**Files:**
- Modify: `backend/jose/schemas.py`

**Interfaces:**
- Consumes: nothing new (pure schema definitions).
- Produces: `JobDecision` (StrEnum: `APPLIED="applied"`, `IRRELEVANT="irrelevant"`, `WATCH="watch"`, `ARCHIVED="archived"`), `JobDecisionUpdate` (field `decision: JobDecision | None`), `JobDecisionRead` (fields `id: uuid.UUID`, `user_decision: str | None`), `JobSourceRead`, `JobVersionRead`, `JobDetailRead` — all used by Task 6 and Task 8's routes.

- [ ] **Step 1: Add the enum and schemas**

In `backend/jose/schemas.py`, after the existing `JobMergeKeep` class, add:

```python
class JobDecision(StrEnum):
    APPLIED = "applied"
    IRRELEVANT = "irrelevant"
    WATCH = "watch"
    ARCHIVED = "archived"


class JobDecisionUpdate(BaseModel):
    decision: JobDecision | None


class JobDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_decision: str | None


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


class JobDetailRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    title: str
    normalized_title: str
    description_text: str | None
    description_html: str | None
    department: str | None
    location: str | None
    remote_type: str | None
    employment_type: str | None
    compensation_min: int | None
    compensation_max: int | None
    currency: str | None
    application_url: str
    canonical_url: str
    ats_type: str | None
    published_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    status: str
    reposted_from_job_id: uuid.UUID | None
    user_decision: str | None
    sources: list[JobSourceRead]
    versions: list[JobVersionRead]
```

- [ ] **Step 2: Confirm the module still imports cleanly**

Run: `docker compose run --rm api python -c "import jose.schemas"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/jose/schemas.py
git commit -m "feat: add job decision and job detail Pydantic schemas"
```

---

### Task 3: `services/jobs.py` — `list_jobs()` with filters

**Files:**
- Create: `backend/jose/services/jobs.py`
- Test: `backend/tests/test_jobs_service.py` (new)

**Interfaces:**
- Consumes: `Job`, `Company`, `JobSource` models (Task 1); `db_session`/`user`/`other_user` fixtures and `_make_company`/`_make_job` helpers from `backend/tests/conftest.py`.
- Produces: `list_jobs(session, user, *, company=None, title=None, source_id=None, date_from=None, date_to=None, location=None, ats_type=None, status=None, decision=None, limit=50, offset=0) -> list[dict[str, Any]]`, each dict with keys `id, company_name, title, location, application_url, ats_type, published_at, first_seen_at, last_seen_at, status, reposted_from_job_id, user_decision`. Also produces `HIDDEN_BY_DEFAULT_DECISIONS = ("irrelevant", "archived")` (reused by Task 4's tests) and `JobNotFoundError` (reused by Tasks 5 and 7).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_jobs_service.py`:

```python
import uuid

from conftest import _make_company, _make_job

from jose.models import JobSource, Source
from jose.services.jobs import list_jobs


def _make_source(session, user, name="Source"):
    source = Source(user_id=user.id, name=name, url=f"https://{uuid.uuid4().hex}.example.com")
    session.add(source)
    session.flush()
    return source


def test_list_jobs_defaults_exclude_irrelevant_and_archived(db_session, user):
    company = _make_company(db_session, user)
    undecided = _make_job(db_session, user, company, application_url="https://a.example.com/1")
    applied = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/2",
        user_decision="applied",
    )
    irrelevant = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/3",
        user_decision="irrelevant",
    )
    archived = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/4",
        user_decision="archived",
    )
    db_session.commit()

    results = list_jobs(db_session, user)

    ids = {row["id"] for row in results}
    assert undecided.id in ids
    assert applied.id in ids
    assert irrelevant.id not in ids
    assert archived.id not in ids


def test_list_jobs_explicit_decision_filter_includes_hidden_defaults(db_session, user):
    company = _make_company(db_session, user)
    irrelevant = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/1",
        user_decision="irrelevant",
    )
    db_session.commit()

    results = list_jobs(db_session, user, decision=["irrelevant"])

    assert {row["id"] for row in results} == {irrelevant.id}


def test_list_jobs_filters_by_company_title_location_ats(db_session, user):
    company_a = _make_company(db_session, user, name="Acme Robotics")
    company_b = _make_company(db_session, user, name="Beta Systems")
    target = _make_job(
        db_session,
        user,
        company_a,
        title="Senior Platform Engineer",
        location="Remote - US",
        ats_type="greenhouse",
        application_url="https://a.example.com/1",
    )
    _make_job(
        db_session,
        user,
        company_b,
        title="Sales Rep",
        location="New York, NY",
        ats_type="lever",
        application_url="https://a.example.com/2",
    )
    db_session.commit()

    assert {row["id"] for row in list_jobs(db_session, user, company="acme")} == {target.id}
    assert {row["id"] for row in list_jobs(db_session, user, title="platform")} == {target.id}
    assert {row["id"] for row in list_jobs(db_session, user, location="remote")} == {target.id}
    assert {row["id"] for row in list_jobs(db_session, user, ats_type="greenhouse")} == {
        target.id
    }


def test_list_jobs_filters_by_source(db_session, user):
    company = _make_company(db_session, user)
    linked = _make_job(db_session, user, company, application_url="https://a.example.com/1")
    unlinked = _make_job(db_session, user, company, application_url="https://a.example.com/2")
    source = _make_source(db_session, user)
    db_session.add(JobSource(user_id=user.id, job_id=linked.id, source_id=source.id))
    db_session.commit()

    results = list_jobs(db_session, user, source_id=source.id)

    ids = {row["id"] for row in results}
    assert linked.id in ids
    assert unlinked.id not in ids


def test_list_jobs_filters_by_date_range(db_session, user):
    from datetime import UTC, datetime

    company = _make_company(db_session, user)
    in_range = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/1",
        first_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    out_of_range = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/2",
        first_seen_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db_session.commit()

    results = list_jobs(db_session, user, date_from="2026-07-01", date_to="2026-07-31")

    ids = {row["id"] for row in results}
    assert in_range.id in ids
    assert out_of_range.id not in ids


def test_list_jobs_pagination(db_session, user):
    company = _make_company(db_session, user)
    for i in range(3):
        _make_job(db_session, user, company, application_url=f"https://a.example.com/{i}")
    db_session.commit()

    page_one = list_jobs(db_session, user, limit=2, offset=0)
    page_two = list_jobs(db_session, user, limit=2, offset=2)

    assert len(page_one) == 2
    assert len(page_two) == 1


def test_list_jobs_isolates_by_user(db_session, user, other_user):
    company = _make_company(db_session, user)
    _make_job(db_session, user, company, application_url="https://a.example.com/1")
    other_company = _make_company(db_session, other_user)
    _make_job(db_session, other_user, other_company, application_url="https://b.example.com/1")
    db_session.commit()

    results = list_jobs(db_session, user)

    assert len(results) == 1
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `docker compose run --rm api pytest tests/test_jobs_service.py -v`
Expected: `ModuleNotFoundError: No module named 'jose.services.jobs'`

- [ ] **Step 3: Implement `list_jobs()`**

Create `backend/jose/services/jobs.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jose.models import Company, Job, JobSource, User

HIDDEN_BY_DEFAULT_DECISIONS = ("irrelevant", "archived")


class JobNotFoundError(Exception):
    pass


def _parse_date_bound(value: str | None, *, end_of_day: bool) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if end_of_day:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def _job_row_to_dict(job: Job, company_name: str) -> dict[str, Any]:
    return {
        "id": job.id,
        "company_name": company_name,
        "title": job.title,
        "location": job.location,
        "application_url": job.application_url,
        "ats_type": job.ats_type,
        "published_at": job.published_at,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "status": job.status,
        "reposted_from_job_id": job.reposted_from_job_id,
        "user_decision": job.user_decision,
    }


def list_jobs(
    session: Session,
    user: User,
    *,
    company: str | None = None,
    title: str | None = None,
    source_id: uuid.UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    ats_type: str | None = None,
    status: str | None = None,
    decision: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = (
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.user_id == user.id, Job.status != "merged")
    )

    if company:
        query = query.where(Company.name.ilike(f"%{company}%"))
    if title:
        query = query.where(Job.title.ilike(f"%{title}%"))
    if location:
        query = query.where(Job.location.ilike(f"%{location}%"))
    if ats_type:
        query = query.where(Job.ats_type == ats_type)
    if status:
        query = query.where(Job.status == status)

    from_bound = _parse_date_bound(date_from, end_of_day=False)
    if from_bound:
        query = query.where(Job.first_seen_at >= from_bound)
    to_bound = _parse_date_bound(date_to, end_of_day=True)
    if to_bound:
        query = query.where(Job.first_seen_at <= to_bound)

    if source_id:
        query = query.where(
            Job.id.in_(
                select(JobSource.job_id).where(
                    JobSource.source_id == source_id, JobSource.user_id == user.id
                )
            )
        )

    if decision:
        query = query.where(Job.user_decision.in_(decision))
    else:
        query = query.where(
            or_(
                Job.user_decision.is_(None),
                Job.user_decision.notin_(HIDDEN_BY_DEFAULT_DECISIONS),
            )
        )

    rows = session.execute(
        query.order_by(Job.first_seen_at.desc()).limit(limit).offset(offset)
    ).all()
    return [_job_row_to_dict(job, company_name) for job, company_name in rows]
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `docker compose run --rm api pytest tests/test_jobs_service.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Lint and commit**

Run: `docker compose run --rm api ruff check jose tests`
Expected: no errors (fix any and re-run before proceeding).

```bash
git add backend/jose/services/jobs.py backend/tests/test_jobs_service.py
git commit -m "feat: add services/jobs.py list_jobs with search/filter support"
```

---

### Task 4: Wire filters into `GET /api/v1/jobs`

**Files:**
- Modify: `backend/jose/api/routes/jobs.py`
- Modify: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `jobs_service.list_jobs(...)` (Task 3).
- Produces: `GET /api/v1/jobs` now accepts `company, title, source_id, date_from, date_to, location, ats_type, status, decision (repeatable), limit (default 50, max 200), offset` query params.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_jobs_api.py`:

```python
def test_list_jobs_api_filters_by_query_params(client, db_session, user):
    company = _make_company(db_session, user, name="Acme Robotics")
    match = _make_job(
        db_session,
        user,
        company,
        title="Platform Engineer",
        application_url="https://acme.example.com/match",
    )
    _make_job(
        db_session,
        user,
        company,
        title="Sales Rep",
        application_url="https://acme.example.com/other",
    )
    db_session.commit()

    response = client.get("/api/v1/jobs", params={"title": "platform"})

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert ids == {str(match.id)}


def test_list_jobs_api_hides_archived_by_default_but_shows_when_requested(
    client, db_session, user
):
    company = _make_company(db_session, user)
    archived = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/archived",
        user_decision="archived",
    )
    db_session.commit()

    default_response = client.get("/api/v1/jobs")
    assert str(archived.id) not in {item["id"] for item in default_response.json()}

    explicit_response = client.get("/api/v1/jobs", params={"decision": "archived"})
    assert str(archived.id) in {item["id"] for item in explicit_response.json()}
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest tests/test_jobs_api.py -v -k 'filters_by_query_params or hides_archived'"`
Expected: FAIL — current route ignores all query params except `limit`, so `title=platform` returns both jobs and the count assertion fails.

- [ ] **Step 3: Update the route**

Replace the full contents of `backend/jose/api/routes/jobs.py`:

```python
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from jose.api.deps import CurrentUser, DBSession
from jose.schemas import JobDecisionRead, JobDecisionUpdate, JobDetailRead
from jose.services import jobs as jobs_service

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    company: str | None = None,
    title: str | None = None,
    source_id: uuid.UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    ats_type: str | None = None,
    status: str | None = None,
    decision: list[str] | None = Query(default=None),
) -> list[dict[str, Any]]:
    return jobs_service.list_jobs(
        db,
        user,
        company=company,
        title=title,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        location=location,
        ats_type=ats_type,
        status=status,
        decision=decision,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobDetailRead)
def get_job(job_id: uuid.UUID, db: DBSession, user: CurrentUser) -> dict[str, Any]:
    try:
        return jobs_service.get_job_detail(db, user, job_id)
    except jobs_service.JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@router.patch("/{job_id}/decision", response_model=JobDecisionRead)
def update_job_decision(
    job_id: uuid.UUID, payload: JobDecisionUpdate, db: DBSession, user: CurrentUser
):
    decision = payload.decision.value if payload.decision is not None else None
    try:
        return jobs_service.set_job_decision(db, user, job_id, decision)
    except jobs_service.JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
```

Note: this adds the `get_job`/`update_job_decision` routes now (referencing `jobs_service.get_job_detail` / `jobs_service.set_job_decision`, which don't exist until Tasks 5 and 7) so the file only needs editing once. They'll 500 until those tasks land — acceptable mid-plan, since this task's tests only exercise `GET /api/v1/jobs`.

- [ ] **Step 4: Run the tests and confirm the list ones pass**

Run: `docker compose run --rm api pytest tests/test_jobs_api.py -v -k 'filters_by_query_params or hides_archived'`
Expected: both new tests PASS. (Don't run the full file yet — `test_list_jobs_excludes_merged_away_jobs` etc. from before should still pass too; verify with the full file run below.)

Run: `docker compose run --rm api pytest tests/test_jobs_api.py -v`
Expected: all tests in the file PASS (existing ones plus the two new ones).

- [ ] **Step 5: Lint and commit**

Run: `docker compose run --rm api ruff check jose tests`

```bash
git add backend/jose/api/routes/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: extend GET /api/v1/jobs with search/filter query params"
```

---

### Task 5: `services/jobs.py` — `get_job_detail()`

**Files:**
- Modify: `backend/jose/services/jobs.py`
- Test: `backend/tests/test_jobs_service.py`

**Interfaces:**
- Consumes: `JobNotFoundError` (Task 3); `JobSource`, `JobVersion`, `Source` models.
- Produces: `get_job_detail(session, user, job_id) -> dict[str, Any]` with keys matching `JobDetailRead` (Task 2): `id, company_name, title, normalized_title, description_text, description_html, department, location, remote_type, employment_type, compensation_min, compensation_max, currency, application_url, canonical_url, ats_type, published_at, first_seen_at, last_seen_at, status, reposted_from_job_id, user_decision, sources (list of dicts with source_id, source_name, source_category, source_job_url, is_active, first_seen_at, last_seen_at), versions (list of dicts with seen_at, is_material, content_hash, newest first)`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_jobs_service.py`:

```python
def test_get_job_detail_includes_sources_and_versions(db_session, user):
    from jose.models import JobSource, JobVersion
    from jose.services.jobs import get_job_detail

    company = _make_company(db_session, user)
    job = _make_job(
        db_session,
        user,
        company,
        application_url="https://a.example.com/1",
        description_text="Build things.",
    )
    source = _make_source(db_session, user, name="Acme Careers")
    db_session.add(
        JobSource(
            user_id=user.id,
            job_id=job.id,
            source_id=source.id,
            source_job_url="https://acme.example.com/jobs/1",
            is_active=True,
        )
    )
    db_session.add(
        JobVersion(
            user_id=user.id,
            job_id=job.id,
            content_hash="hash-1",
            snapshot={"title": job.title},
            is_material=True,
        )
    )
    db_session.commit()

    detail = get_job_detail(db_session, user, job.id)

    assert detail["id"] == job.id
    assert detail["company_name"] == company.name
    assert detail["description_text"] == "Build things."
    assert len(detail["sources"]) == 1
    assert detail["sources"][0]["source_name"] == "Acme Careers"
    assert detail["sources"][0]["source_job_url"] == "https://acme.example.com/jobs/1"
    assert len(detail["versions"]) == 1
    assert detail["versions"][0]["content_hash"] == "hash-1"


def test_get_job_detail_raises_for_missing_job(db_session, user):
    import uuid

    from jose.services.jobs import JobNotFoundError, get_job_detail

    with pytest.raises(JobNotFoundError):
        get_job_detail(db_session, user, uuid.uuid4())


def test_get_job_detail_rejects_other_user(db_session, user, other_user):
    from jose.services.jobs import JobNotFoundError, get_job_detail

    company = _make_company(db_session, other_user)
    job = _make_job(db_session, other_user, company, application_url="https://a.example.com/1")
    db_session.commit()

    with pytest.raises(JobNotFoundError):
        get_job_detail(db_session, user, job.id)
```

Add `import pytest` at the top of `backend/tests/test_jobs_service.py` (needed for `pytest.raises`).

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `docker compose run --rm api pytest tests/test_jobs_service.py -v -k get_job_detail`
Expected: FAIL — `ImportError: cannot import name 'get_job_detail'`.

- [ ] **Step 3: Implement `get_job_detail()`**

In `backend/jose/services/jobs.py`, update the import line and append the function:

```python
from jose.models import Company, Job, JobSource, JobVersion, Source, User
```

```python
def get_job_detail(session: Session, user: User, job_id: uuid.UUID) -> dict[str, Any]:
    row = session.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.id == job_id, Job.user_id == user.id)
    ).first()
    if row is None:
        raise JobNotFoundError(str(job_id))
    job, company_name = row

    source_rows = session.execute(
        select(JobSource, Source.name, Source.category)
        .join(Source, Source.id == JobSource.source_id)
        .where(JobSource.job_id == job.id, JobSource.user_id == user.id)
        .order_by(JobSource.first_seen_at)
    ).all()
    sources = [
        {
            "source_id": link.source_id,
            "source_name": source_name,
            "source_category": source_category,
            "source_job_url": link.source_job_url,
            "is_active": link.is_active,
            "first_seen_at": link.first_seen_at,
            "last_seen_at": link.last_seen_at,
        }
        for link, source_name, source_category in source_rows
    ]

    versions = [
        {
            "seen_at": version.seen_at,
            "is_material": version.is_material,
            "content_hash": version.content_hash,
        }
        for version in session.scalars(
            select(JobVersion)
            .where(JobVersion.job_id == job.id)
            .order_by(JobVersion.seen_at.desc())
        ).all()
    ]

    return {
        "id": job.id,
        "company_name": company_name,
        "title": job.title,
        "normalized_title": job.normalized_title,
        "description_text": job.description_text,
        "description_html": job.description_html,
        "department": job.department,
        "location": job.location,
        "remote_type": job.remote_type,
        "employment_type": job.employment_type,
        "compensation_min": job.compensation_min,
        "compensation_max": job.compensation_max,
        "currency": job.currency,
        "application_url": job.application_url,
        "canonical_url": job.canonical_url,
        "ats_type": job.ats_type,
        "published_at": job.published_at,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "status": job.status,
        "reposted_from_job_id": job.reposted_from_job_id,
        "user_decision": job.user_decision,
        "sources": sources,
        "versions": versions,
    }
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `docker compose run --rm api pytest tests/test_jobs_service.py -v`
Expected: all tests (Task 3's + Task 5's) PASS.

- [ ] **Step 5: Lint and commit**

Run: `docker compose run --rm api ruff check jose tests`

```bash
git add backend/jose/services/jobs.py backend/tests/test_jobs_service.py
git commit -m "feat: add get_job_detail service with source lineage and version history"
```

---

### Task 6: Verify `GET /api/v1/jobs/{job_id}` at the API level

**Files:**
- Modify: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: the route added in Task 4 (`get_job`), which calls `jobs_service.get_job_detail` (Task 5).

The route itself was already written in Task 4 (to avoid touching `routes/jobs.py` twice); this task only adds its test coverage now that `get_job_detail` exists.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_jobs_api.py`:

```python
def _make_source(session, user, name="Source"):
    import uuid

    from jose.models import Source

    source = Source(user_id=user.id, name=name, url=f"https://{uuid.uuid4().hex}.example.com")
    session.add(source)
    session.flush()
    return source


def test_get_job_detail_api_returns_sources_and_versions(client, db_session, user):
    from jose.models import JobSource

    company = _make_company(db_session, user)
    job = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/1",
        description_text="Build things.",
    )
    source = _make_source(db_session, user, name="Acme Careers")
    db_session.add(
        JobSource(user_id=user.id, job_id=job.id, source_id=source.id, is_active=True)
    )
    db_session.commit()

    response = client.get(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["description_text"] == "Build things."
    assert len(body["sources"]) == 1
    assert body["sources"][0]["source_name"] == "Acme Careers"
    assert body["versions"] == []


def test_get_job_detail_api_404_for_missing_job(client):
    import uuid

    response = client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_job_detail_api_404_for_other_users_job(client, db_session, other_user):
    company = _make_company(db_session, other_user)
    job = _make_job(db_session, other_user, company, application_url="https://b.example.com/1")
    db_session.commit()

    response = client.get(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 404
```

`_make_source` here is a local copy of the same helper defined in `test_jobs_service.py` (Task 3) — this repo's convention is a local copy per test file (see `test_job_merge_service.py`'s and `test_job_change_removal.py`'s own `_make_source`), not a shared fixture, so duplicating it here matches existing style.

- [ ] **Step 2: Run the tests and confirm they pass**

Run: `docker compose run --rm api pytest tests/test_jobs_api.py -v`
Expected: all tests in the file PASS, including the 3 new ones.

- [ ] **Step 3: Lint and commit**

Run: `docker compose run --rm api ruff check jose tests`

```bash
git add backend/tests/test_jobs_api.py
git commit -m "test: cover GET /api/v1/jobs/{id} detail endpoint"
```

---

### Task 7: `services/jobs.py` — `set_job_decision()`

**Files:**
- Modify: `backend/jose/services/jobs.py`
- Test: `backend/tests/test_jobs_service.py`

**Interfaces:**
- Consumes: `JobNotFoundError` (Task 3); `SystemEvent` model.
- Produces: `set_job_decision(session, user, job_id, decision: str | None) -> Job` (returns the updated ORM `Job`; raises `JobNotFoundError` for missing/foreign jobs). Writes one `SystemEvent(event_type="job_decision_set", entity_type="job", entity_id=job.id, data={"previous": ..., "decision": ...})` per call.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_jobs_service.py`:

```python
def test_set_job_decision_updates_job_and_writes_audit_event(db_session, user):
    from sqlalchemy import select

    from jose.models import SystemEvent
    from jose.services.jobs import set_job_decision

    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company, application_url="https://a.example.com/1")
    db_session.commit()

    updated = set_job_decision(db_session, user, job.id, "applied")

    assert updated.user_decision == "applied"

    event = db_session.scalar(
        select(SystemEvent).where(
            SystemEvent.event_type == "job_decision_set", SystemEvent.entity_id == job.id
        )
    )
    assert event is not None
    assert event.data == {"previous": None, "decision": "applied"}


def test_set_job_decision_clears_with_none_and_records_previous(db_session, user):
    from sqlalchemy import select

    from jose.models import SystemEvent
    from jose.services.jobs import set_job_decision

    company = _make_company(db_session, user)
    job = _make_job(
        db_session, user, company, application_url="https://a.example.com/1", user_decision="watch"
    )
    db_session.commit()

    updated = set_job_decision(db_session, user, job.id, None)

    assert updated.user_decision is None

    event = db_session.scalar(
        select(SystemEvent).where(
            SystemEvent.event_type == "job_decision_set", SystemEvent.entity_id == job.id
        )
    )
    assert event.data == {"previous": "watch", "decision": None}


def test_set_job_decision_raises_for_missing_job(db_session, user):
    import uuid

    from jose.services.jobs import JobNotFoundError, set_job_decision

    with pytest.raises(JobNotFoundError):
        set_job_decision(db_session, user, uuid.uuid4(), "applied")


def test_set_job_decision_rejects_other_user(db_session, user, other_user):
    from jose.services.jobs import JobNotFoundError, set_job_decision

    company = _make_company(db_session, other_user)
    job = _make_job(db_session, other_user, company, application_url="https://a.example.com/1")
    db_session.commit()

    with pytest.raises(JobNotFoundError):
        set_job_decision(db_session, user, job.id, "applied")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `docker compose run --rm api pytest tests/test_jobs_service.py -v -k set_job_decision`
Expected: FAIL — `ImportError: cannot import name 'set_job_decision'`.

- [ ] **Step 3: Implement `set_job_decision()`**

In `backend/jose/services/jobs.py`, update the import line and append the function:

```python
from jose.models import Company, Job, JobSource, JobVersion, Source, SystemEvent, User
```

```python
def set_job_decision(
    session: Session, user: User, job_id: uuid.UUID, decision: str | None
) -> Job:
    job = session.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if job is None:
        raise JobNotFoundError(str(job_id))

    previous = job.user_decision
    job.user_decision = decision
    session.add(
        SystemEvent(
            user_id=user.id,
            event_type="job_decision_set",
            entity_type="job",
            entity_id=job.id,
            message=f"Job decision set to {decision!r} (was {previous!r})",
            data={"previous": previous, "decision": decision},
        )
    )
    session.commit()
    session.refresh(job)
    return job
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `docker compose run --rm api pytest tests/test_jobs_service.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Lint and commit**

Run: `docker compose run --rm api ruff check jose tests`

```bash
git add backend/jose/services/jobs.py backend/tests/test_jobs_service.py
git commit -m "feat: add set_job_decision service with SystemEvent audit trail"
```

---

### Task 8: Verify `PATCH /api/v1/jobs/{job_id}/decision` at the API level

**Files:**
- Modify: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: the route added in Task 4 (`update_job_decision`), which calls `jobs_service.set_job_decision` (Task 7).

Same situation as Task 6 — the route already exists from Task 4; this adds its tests now that the service function it depends on is implemented.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_jobs_api.py`:

```python
def test_update_job_decision_api_sets_and_clears(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    db_session.commit()

    set_response = client.patch(
        f"/api/v1/jobs/{job.id}/decision", json={"decision": "watch"}
    )
    assert set_response.status_code == 200
    assert set_response.json()["user_decision"] == "watch"

    clear_response = client.patch(f"/api/v1/jobs/{job.id}/decision", json={"decision": None})
    assert clear_response.status_code == 200
    assert clear_response.json()["user_decision"] is None


def test_update_job_decision_api_rejects_invalid_value(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    db_session.commit()

    response = client.patch(
        f"/api/v1/jobs/{job.id}/decision", json={"decision": "not-a-real-decision"}
    )

    assert response.status_code == 422


def test_update_job_decision_api_404_for_other_users_job(client, db_session, other_user):
    company = _make_company(db_session, other_user)
    job = _make_job(db_session, other_user, company, application_url="https://b.example.com/1")
    db_session.commit()

    response = client.patch(f"/api/v1/jobs/{job.id}/decision", json={"decision": "applied"})

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests and confirm they pass**

Run: `docker compose run --rm api pytest tests/test_jobs_api.py -v`
Expected: all tests in the file PASS, including the 3 new ones.

- [ ] **Step 3: Lint and commit**

Run: `docker compose run --rm api ruff check jose tests`

```bash
git add backend/tests/test_jobs_api.py
git commit -m "test: cover PATCH /api/v1/jobs/{id}/decision endpoint"
```

---

### Task 9: Frontend API client — types, `getJobs(filters)`, `getJob(id)`

**Files:**
- Modify: `web/lib/api.ts`

**Interfaces:**
- Produces: `Job` type gains `user_decision: string | null`. New types `JobFilters`, `JobSourceLineage`, `JobVersionEntry`, `JobDetail`. New functions `getJobs(filters?: JobFilters): Promise<Job[]>` (replaces the old zero-arg `getJobs`) and `getJob(id: string): Promise<JobDetail>`.

- [ ] **Step 1: Update the `Job` type and add new types**

In `web/lib/api.ts`, update `Job` and add the new types right after it:

```ts
export type Job = {
  id: string;
  company_name: string;
  title: string;
  location: string | null;
  application_url: string;
  ats_type: string | null;
  published_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  status: string;
  user_decision: string | null;
};

export type JobFilters = {
  company?: string;
  title?: string;
  source_id?: string;
  date_from?: string;
  date_to?: string;
  location?: string;
  ats_type?: string;
  status?: string;
  decision?: string[];
  limit?: number;
  offset?: number;
};

export type JobSourceLineage = {
  source_id: string;
  source_name: string;
  source_category: string;
  source_job_url: string | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
};

export type JobVersionEntry = {
  seen_at: string;
  is_material: boolean;
  content_hash: string;
};

export type JobDetail = Job & {
  normalized_title: string;
  description_text: string | null;
  department: string | null;
  remote_type: string | null;
  employment_type: string | null;
  compensation_min: number | null;
  compensation_max: number | null;
  currency: string | null;
  canonical_url: string;
  sources: JobSourceLineage[];
  versions: JobVersionEntry[];
};
```

- [ ] **Step 2: Replace `getJobs` and add `getJob`**

Replace the existing `getJobs` function:

```ts
function buildJobsQuery(filters: JobFilters): string {
  const params = new URLSearchParams();
  if (filters.company) params.set("company", filters.company);
  if (filters.title) params.set("title", filters.title);
  if (filters.source_id) params.set("source_id", filters.source_id);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.location) params.set("location", filters.location);
  if (filters.ats_type) params.set("ats_type", filters.ats_type);
  if (filters.status) params.set("status", filters.status);
  for (const decision of filters.decision ?? []) {
    params.append("decision", decision);
  }
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

export async function getJobs(filters: JobFilters = {}): Promise<Job[]> {
  return getJson<Job[]>(`/api/v1/jobs?${buildJobsQuery(filters)}`);
}

export async function getJob(id: string): Promise<JobDetail> {
  return getJson<JobDetail>(`/api/v1/jobs/${id}`);
}
```

- [ ] **Step 3: Verify the frontend still typechecks**

Run: `docker compose run --rm web npm run lint`
Expected: this will currently FAIL — `web/app/jobs/page.tsx` still calls the old `getJobs()` shape and doesn't yet use `user_decision`, but since `getJobs` now takes an optional argument the zero-arg call still compiles. The real failure, if any, will be about `Job`'s new required-shaped usage elsewhere; there are no other callers of `Job`/`getJobs` today besides `jobs/page.tsx`, which Task 12 rewrites. Confirm the only lint errors (if any) are inside `web/app/jobs/page.tsx`; if lint is otherwise clean, proceed — Task 12 fixes that file.

- [ ] **Step 4: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat: add job filter/detail types and API client functions"
```

---

### Task 10: `job-filters.tsx` client component

**Files:**
- Create: `web/components/job-filters.tsx`

**Interfaces:**
- Consumes: `next/navigation`'s `useRouter`, `usePathname`, `useSearchParams`.
- Produces: `JobFilters({ sources }: { sources: { id: string; name: string }[] })` — a `"use client"` component that renders filter inputs, reads initial values from the current URL, and on submit pushes a new URL with query params (consumed by Task 12's `jobs/page.tsx`, which reads `searchParams`).

- [ ] **Step 1: Write the component**

Create `web/components/job-filters.tsx`:

```tsx
"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

const ATS_TYPES = ["ashby", "greenhouse", "lever", "jsonld", "generic"];
const STATUSES = ["active", "removed"];
const DECISIONS = ["applied", "irrelevant", "watch", "archived"];

type SourceOption = { id: string; name: string };

export function JobFilters({ sources }: { sources: SourceOption[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [company, setCompany] = useState(searchParams.get("company") ?? "");
  const [title, setTitle] = useState(searchParams.get("title") ?? "");
  const [location, setLocation] = useState(searchParams.get("location") ?? "");
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") ?? "");
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") ?? "");
  const [sourceId, setSourceId] = useState(searchParams.get("source_id") ?? "");
  const [atsType, setAtsType] = useState(searchParams.get("ats_type") ?? "");
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [decision, setDecision] = useState(searchParams.get("decision") ?? "");

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (company) params.set("company", company);
    if (title) params.set("title", title);
    if (location) params.set("location", location);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (sourceId) params.set("source_id", sourceId);
    if (atsType) params.set("ats_type", atsType);
    if (status) params.set("status", status);
    if (decision) params.set("decision", decision);
    router.push(params.toString() ? `${pathname}?${params.toString()}` : pathname);
  }

  function resetFilters() {
    setCompany("");
    setTitle("");
    setLocation("");
    setDateFrom("");
    setDateTo("");
    setSourceId("");
    setAtsType("");
    setStatus("");
    setDecision("");
    router.push(pathname);
  }

  const hasActiveFilters = Boolean(
    company || title || location || dateFrom || dateTo || sourceId || atsType || status || decision,
  );

  return (
    <form className="tableFilters" onSubmit={applyFilters}>
      <input
        type="search"
        placeholder="Company"
        value={company}
        onChange={(event) => setCompany(event.target.value)}
      />
      <input
        type="search"
        placeholder="Title"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
      />
      <input
        type="search"
        placeholder="Location"
        value={location}
        onChange={(event) => setLocation(event.target.value)}
      />
      <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
        <option value="">All sources</option>
        {sources.map((source) => (
          <option key={source.id} value={source.id}>
            {source.name}
          </option>
        ))}
      </select>
      <select value={atsType} onChange={(event) => setAtsType(event.target.value)}>
        <option value="">All ATS types</option>
        {ATS_TYPES.map((type) => (
          <option key={type} value={type}>
            {type}
          </option>
        ))}
      </select>
      <select value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="">All statuses</option>
        {STATUSES.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <select value={decision} onChange={(event) => setDecision(event.target.value)}>
        <option value="">Needs review (default)</option>
        {DECISIONS.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <input
        type="date"
        aria-label="From date"
        value={dateFrom}
        onChange={(event) => setDateFrom(event.target.value)}
      />
      <input
        type="date"
        aria-label="To date"
        value={dateTo}
        onChange={(event) => setDateTo(event.target.value)}
      />
      <button type="submit">Apply filters</button>
      {hasActiveFilters ? (
        <button type="button" className="ghostButton" onClick={resetFilters}>
          Reset filters
        </button>
      ) : null}
    </form>
  );
}
```

- [ ] **Step 2: Lint**

Run: `docker compose run --rm web npm run lint`
Expected: no new errors attributable to `job-filters.tsx` (this file isn't imported anywhere yet, so it won't affect the build; only lint runs against it directly).

- [ ] **Step 3: Commit**

```bash
git add web/components/job-filters.tsx
git commit -m "feat: add JobFilters client component"
```

---

### Task 11: `job-decision-controls.tsx` client component

**Files:**
- Create: `web/components/job-decision-controls.tsx`

**Interfaces:**
- Consumes: `apiFetchJson` from `web/lib/browser-api.ts`.
- Produces: `JobDecisionControls({ jobId, decision, onChange }: { jobId: string; decision: string | null; onChange: (decision: string | null) => void })` — renders one button per decision value; clicking the currently-active one clears the decision (toggle-off); calls `PATCH /api/v1/jobs/{jobId}/decision` and invokes `onChange` with the server-confirmed value. Consumed by Tasks 12 and 13.

- [ ] **Step 1: Write the component**

Create `web/components/job-decision-controls.tsx`:

```tsx
"use client";

import { useState } from "react";
import { apiFetchJson } from "@/lib/browser-api";

const DECISIONS: { value: string; label: string }[] = [
  { value: "applied", label: "Applied" },
  { value: "irrelevant", label: "Irrelevant" },
  { value: "watch", label: "Watch" },
  { value: "archived", label: "Archived" },
];

export function JobDecisionControls({
  jobId,
  decision,
  onChange,
}: {
  jobId: string;
  decision: string | null;
  onChange: (decision: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function setDecision(next: string | null) {
    setError(null);
    setBusy(true);
    try {
      const updated = await apiFetchJson<{ id: string; user_decision: string | null }>(
        `/api/v1/jobs/${jobId}/decision`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: next }),
        },
      );
      onChange(updated.user_decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rowActions">
      {DECISIONS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          className={decision === value ? "" : "ghostButton"}
          disabled={busy}
          onClick={() => setDecision(decision === value ? null : value)}
        >
          {label}
        </button>
      ))}
      {error ? <span className="formError">{error}</span> : null}
    </div>
  );
}
```

- [ ] **Step 2: Lint**

Run: `docker compose run --rm web npm run lint`
Expected: no new errors attributable to `job-decision-controls.tsx`.

- [ ] **Step 3: Commit**

```bash
git add web/components/job-decision-controls.tsx
git commit -m "feat: add JobDecisionControls client component"
```

---

### Task 12: Rework `jobs/page.tsx` into a filtered, paginated, decision-aware list

**Files:**
- Create: `web/components/jobs-table.tsx`
- Modify: `web/app/jobs/page.tsx`

**Interfaces:**
- Consumes: `getJobs`, `getSources`, `Job`, `JobFilters` type (Task 9); `JobFilters` component (Task 10); `JobDecisionControls` (Task 11).
- Produces: `JobsTable({ initialJobs }: { initialJobs: Job[] })` client component (holds local decision state per row for optimistic button highlighting). `jobs/page.tsx` reads `searchParams`, builds a `JobFilters` (the `lib/api.ts` type) object, fetches jobs + sources in parallel, and renders the filter form, table, and Prev/Next pagination links.

- [ ] **Step 1: Create `jobs-table.tsx`**

Create `web/components/jobs-table.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import type { Job } from "@/lib/api";
import { JobDecisionControls } from "@/components/job-decision-controls";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "Unknown";
}

export function JobsTable({ initialJobs }: { initialJobs: Job[] }) {
  const [jobs, setJobs] = useState(initialJobs);

  function updateDecision(jobId: string, decision: string | null) {
    setJobs((current) =>
      current.map((job) => (job.id === jobId ? { ...job, user_decision: decision } : job)),
    );
  }

  if (!jobs.length) {
    return <p className="emptyState">No jobs match the current filters.</p>;
  }

  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Company</th>
            <th>Title</th>
            <th>Location</th>
            <th>ATS</th>
            <th>First seen</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>{job.company_name}</td>
              <td>
                <Link href={`/jobs/${job.id}`}>{job.title}</Link>
              </td>
              <td>{job.location ?? "Location not listed"}</td>
              <td>
                <code>{job.ats_type ?? "web"}</code>
              </td>
              <td>{formatDate(job.first_seen_at)}</td>
              <td>
                <JobDecisionControls
                  jobId={job.id}
                  decision={job.user_decision}
                  onChange={(decision) => updateDecision(job.id, decision)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Replace `web/app/jobs/page.tsx`**

```tsx
import Link from "next/link";
import { JobFilters } from "@/components/job-filters";
import { JobsTable } from "@/components/jobs-table";
import { getJobs, getSources } from "@/lib/api";
import type { JobFilters as JobFiltersType } from "@/lib/api";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type RawSearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function toFilters(searchParams: RawSearchParams): JobFiltersType {
  const decision = first(searchParams.decision);
  const offset = first(searchParams.offset);
  return {
    company: first(searchParams.company),
    title: first(searchParams.title),
    source_id: first(searchParams.source_id),
    date_from: first(searchParams.date_from),
    date_to: first(searchParams.date_to),
    location: first(searchParams.location),
    ats_type: first(searchParams.ats_type),
    status: first(searchParams.status),
    decision: decision ? [decision] : undefined,
    limit: PAGE_SIZE,
    offset: offset ? Number(offset) : 0,
  };
}

function pageHref(searchParams: RawSearchParams, offset: number): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (key === "offset" || typeof value !== "string") continue;
    params.set(key, value);
  }
  if (offset > 0) params.set("offset", String(offset));
  const query = params.toString();
  return query ? `/jobs?${query}` : "/jobs";
}

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const filters = toFilters(resolvedSearchParams);
  const [jobs, sources] = await Promise.all([getJobs(filters), getSources()]);
  const offset = filters.offset ?? 0;

  return (
    <section>
      <div className="pageHeader">
        <div>
          <p className="eyebrow">Normalized opportunities</p>
          <h1>Jobs</h1>
          <p>One canonical record per opportunity, even when several sources find it.</p>
        </div>
        <div className="rowActions">
          <Link className="primaryAction ghostButton" href="/jobs/review">
            Review possible duplicates
          </Link>
          <span className="countPill">{jobs.length} shown</span>
        </div>
      </div>

      <JobFilters sources={sources.map((source) => ({ id: source.id, name: source.name }))} />

      <JobsTable initialJobs={jobs} />

      <div className="rowActions" style={{ marginTop: "1rem" }}>
        {offset > 0 ? (
          <Link
            className="ghostButton"
            href={pageHref(resolvedSearchParams, Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </Link>
        ) : null}
        {jobs.length === PAGE_SIZE ? (
          <Link className="ghostButton" href={pageHref(resolvedSearchParams, offset + PAGE_SIZE)}>
            Next
          </Link>
        ) : null}
      </div>
    </section>
  );
}
```

This removes the `.jobGrid`/`.jobCard` layout in favor of the table layout used by `sources`/`source-manager.tsx`, for consistency with the rest of the app and to make room for the decision-controls column.

- [ ] **Step 3: Lint and build**

Run: `docker compose run --rm web npm run lint`
Expected: no errors.

Run: `docker compose run --rm -v /app/.next web npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual verification**

With the stack running (`docker compose ps` should show `web`/`api`/`db` healthy), open `http://localhost:3000/jobs` in a browser:
- Confirm the job list renders with the new table layout and filter row.
- Type a company/title/location substring and click "Apply filters" — confirm the URL gains query params and the list narrows.
- Click a decision button (e.g. "Watch") on a row — confirm it highlights and no error banner appears.
- Reload the page — confirm the list still reflects server state consistent with what was set (the default filter should still show it, since "watch" isn't hidden by default).

- [ ] **Step 5: Commit**

```bash
git add web/components/jobs-table.tsx web/app/jobs/page.tsx
git commit -m "feat: rework jobs list with server-side filters and decision controls"
```

---

### Task 13: Job detail page

**Files:**
- Create: `web/app/jobs/[id]/page.tsx`

**Interfaces:**
- Consumes: `getJob` (Task 9), `JobDecisionControls` (Task 11).

- [ ] **Step 1: Write the page**

Create `web/app/jobs/[id]/page.tsx`:

```tsx
import Link from "next/link";
import { revalidatePath } from "next/cache";
import { JobDecisionControls } from "@/components/job-decision-controls";
import { getJob } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Unknown";
}

export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  async function refreshJobDecision() {
    "use server";
    revalidatePath(`/jobs/${id}`);
  }

  try {
    const job = await getJob(id);

    return (
      <section>
        <div className="pageHeader">
          <div>
            <p className="eyebrow">{job.company_name}</p>
            <h1>{job.title}</h1>
            <p>{job.location ?? "Location not listed"}</p>
          </div>
          <div className="rowActions">
            <a
              className="primaryAction"
              href={job.application_url}
              rel="noreferrer"
              target="_blank"
            >
              Open original posting
            </a>
            <Link className="ghostButton" href="/jobs">
              Back to jobs
            </Link>
          </div>
        </div>

        <div className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panelHeader">
            <h2>Your decision</h2>
          </div>
          <JobDecisionControls jobId={job.id} decision={job.user_decision} onChange={refreshJobDecision} />
        </div>

        <dl className="kvGrid">
          <div className="kvItem">
            <dt>ATS</dt>
            <dd>
              <code>{job.ats_type ?? "web"}</code>
            </dd>
          </div>
          <div className="kvItem">
            <dt>First seen</dt>
            <dd>{formatDate(job.first_seen_at)}</dd>
          </div>
          <div className="kvItem">
            <dt>Last seen</dt>
            <dd>{formatDate(job.last_seen_at)}</dd>
          </div>
        </dl>

        <div className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panelHeader">
            <h2>Description</h2>
          </div>
          {job.description_text ? (
            <pre style={{ whiteSpace: "pre-wrap" }}>{job.description_text}</pre>
          ) : (
            <p className="emptyState">No description captured for this job.</p>
          )}
        </div>

        <div className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panelHeader">
            <h2>Source lineage</h2>
            <span className="countPill">{job.sources.length} sources</span>
          </div>
          {job.sources.length === 0 ? (
            <p className="emptyState">No source lineage recorded.</p>
          ) : (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Category</th>
                    <th>Status</th>
                    <th>First seen</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {job.sources.map((source) => (
                    <tr key={source.source_id}>
                      <td>
                        {source.source_job_url ? (
                          <a href={source.source_job_url} rel="noreferrer" target="_blank">
                            {source.source_name}
                          </a>
                        ) : (
                          source.source_name
                        )}
                      </td>
                      <td>{source.source_category.replaceAll("_", " ")}</td>
                      <td>
                        {source.is_active ? (
                          <span className="status good">Active</span>
                        ) : (
                          <span className="status neutral">Inactive</span>
                        )}
                      </td>
                      <td>{formatDate(source.first_seen_at)}</td>
                      <td>{formatDate(source.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panelHeader">
            <h2>Version history</h2>
            <span className="countPill">{job.versions.length} versions</span>
          </div>
          {job.versions.length === 0 ? (
            <p className="emptyState">No version history recorded.</p>
          ) : (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Seen</th>
                    <th>Change type</th>
                  </tr>
                </thead>
                <tbody>
                  {job.versions.map((version) => (
                    <tr key={version.content_hash}>
                      <td>{formatDate(version.seen_at)}</td>
                      <td>
                        {version.is_material ? (
                          <span className="status warn">Material change</span>
                        ) : (
                          <span className="status neutral">Formatting only</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    );
  } catch (error) {
    return (
      <section className="panel apiError">
        <p className="eyebrow">Job unavailable</p>
        <h1>This job could not be loaded.</h1>
        <p>
          It may not exist, or the JOSE API may be unreachable. <Link href="/jobs">Back to jobs</Link>.
        </p>
        <pre>{error instanceof Error ? error.message : "Unknown error"}</pre>
      </section>
    );
  }
}
```

Note: `description_html` is deliberately not rendered anywhere (see Global Constraints) — only `description_text` is shown.

Note: `onChange` must be a Server Action (`"use server"`), not a plain closure — Next.js 15's Server/Client Component boundary rejects ordinary functions as props passed from a Server Component into a `"use client"` component (`JobDecisionControls`), throwing "Event handlers cannot be passed to Client Component props" at request time (this doesn't fail `next build`'s type-check, only actual rendering). `refreshJobDecision` above calls `revalidatePath` so the page re-fetches `job.user_decision` and the decision buttons highlight correctly after a click, since this Server Component holds no client-side state of its own. (Discovered and fixed during Task 13's implementation — corrected here after the fact.)

- [ ] **Step 2: Lint and build**

Run: `docker compose run --rm web npm run lint`
Expected: no errors.

Run: `docker compose run --rm -v /app/.next web npm run build`
Expected: build succeeds.

- [ ] **Step 3: Manual verification**

With the stack running, click into a job from `http://localhost:3000/jobs`:
- Confirm the detail page loads with description, source lineage table, and version history table (empty states render correctly for jobs with no versions).
- Click a decision button — confirm it highlights with no error.
- Navigate to a nonexistent job id (e.g. `/jobs/00000000-0000-0000-0000-000000000000`) — confirm the "Job unavailable" panel renders instead of a crash.

- [ ] **Step 4: Commit**

```bash
git add web/app/jobs/[id]/page.tsx
git commit -m "feat: add job detail page with lineage, version history, and decisions"
```

---

### Task 14: Full verification pass

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend suite**

Run: `make test`
Expected: all tests pass, including every test added in Tasks 3, 5, 6, 7, 8.

- [ ] **Step 2: Run backend lint**

Run: `docker compose run --rm api ruff check jose tests`
Expected: no errors.

- [ ] **Step 3: Run frontend lint and build**

Run: `docker compose run --rm web npm run lint`
Run: `docker compose run --rm -v /app/.next web npm run build`
Expected: both succeed.

- [ ] **Step 4: Manual end-to-end browser pass**

Against the running dev stack (`http://localhost:3000/jobs`):
- Apply each filter individually (company, title, location, source, ATS, status, date range) and confirm the list narrows correctly; reset filters and confirm the full default list returns.
- Set each of the four decisions (applied, irrelevant, watch, archived) on a job from the list page; confirm irrelevant/archived jobs disappear after navigating away and back (default filter excludes them) and reappear when the decision filter is explicitly set to that value.
- Open a job detail page, set a decision from there, and confirm it's reflected.
- Confirm no browser console errors appear during any of the above (check via the browser devtools or `mcp__claude-in-chrome__read_console_messages` if using Claude in Chrome for this pass).

- [ ] **Step 5: Confirm definition of done**

Cross-check against `docs/superpowers/specs/2026-07-30-jobs-review-foundation-design.md`'s "Definition of done" section — all items should now be satisfied. No commit for this task (verification only); if any check fails, fix it in place as part of the task that owns the affected file and re-run this task.
