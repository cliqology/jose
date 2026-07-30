# Job Change and Removal Detection (Issue 08) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accurately identify changed, removed, and reposted jobs per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 08 and `docs/superpowers/specs/2026-07-30-job-change-removal-detection-design.md`.

**Architecture:** `JobSource` gains `is_active`/`removed_at`; a per-run sweep in `collect_source` (`backend/jose/services/collection.py`) flips a source's links inactive when a successful run stops finding them, and marks a `Job` `"removed"` once it has zero active links across every source. `_upsert_job` gains a `material_hash` comparison (new helper in `collectors/utils.py`) so each `JobVersion` is tagged `is_material` — a formatting-only edit (whitespace/markup) never trips it. `_find_fuzzy_candidate` is generalized to search either `"active"` jobs (existing Tier 2 dup-review behavior, unchanged) or `"removed"` jobs (new: auto-sets `Job.reposted_from_job_id`, no review queue, since it's purely additive lineage). The dashboard and jobs API surface the new counts/field.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, pytest. All backend commands run via `docker compose run --rm api ...` (Colima-backed Docker per `[[docker_environment_colima]]`).

## Global Constraints

- Never invent career facts, dates, metrics, titles, employers, compensation, or personal information — unknown stays unknown (CLAUDE.md rule #3/#4).
- A failed collector is a failure, never a successful zero-result run (CLAUDE.md rule #5) — the removal sweep only runs on the success path of `collect_source`, inside the same `try` block that leads to `run.status = "success"`; any exception is caught by the existing `except Exception` handler (rolls back, marks the run `"failed"`) before the sweep ever runs.
- Apply deterministic filters before paid AI calls (CLAUDE.md rule #6) — material-vs-formatting classification and repost linking are both pure `difflib`/hash comparisons, no AI/embedding calls.
- Every user-owned record includes `user_id`; use timezone-aware UTC datetimes; use UUID primary keys (CLAUDE.md architecture rules).
- Add a migration whenever the persisted schema changes (CLAUDE.md working rule).
- Use fixtures for collector/service tests. No live network calls in unit tests.
- Ruff must pass (line length 100, rules E/F/I/B/UP/SIM per `backend/pyproject.toml`).
- Definition of done: acceptance criteria met, unit tests pass, ruff passes, migration included, error paths handled, no unsupported claim or hidden automation introduced.
- Removal timing is immediate — no grace period across multiple runs (approved design decision; Issues 03/04 already hardened collectors to fail loudly rather than return a truncated success).

---

## Task 1: Data model — `JobSource` active/removed state, `Job.reposted_from_job_id`, `JobVersion.is_material`

**Files:**
- Modify: `backend/jose/models/core.py:145-174` (`JobSource` and `JobVersion` classes), `:104-142` (`Job` class)
- Create: `backend/alembic/versions/0006_job_change_removal_detection.py`
- Test: `backend/tests/test_job_change_removal.py` (new file)

**Interfaces:**
- Consumes: nothing from earlier tasks (first task).
- Produces: `JobSource.is_active: bool`, `JobSource.removed_at: datetime | None`, `Job.reposted_from_job_id: uuid.UUID | None`, `JobVersion.is_material: bool`. Every later task relies on these four columns existing on the ORM models.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_job_change_removal.py`:

```python
import uuid

from jose.models import JobSource, JobVersion

from conftest import _make_company, _make_job


def test_job_source_defaults_to_active(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    link = JobSource(user_id=user.id, job_id=job.id, source_id=uuid.uuid4())
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    assert link.is_active is True
    assert link.removed_at is None


def test_job_reposted_from_job_id_defaults_to_none(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)

    assert job.reposted_from_job_id is None


def test_job_version_defaults_to_material(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    version = JobVersion(user_id=user.id, job_id=job.id, content_hash="hash-1", snapshot={"a": 1})
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)

    assert version.is_material is True
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_change_removal.py -v`
Expected: FAIL — `AttributeError` on `link.is_active`, `job.reposted_from_job_id`, and `version.is_material` (none of these columns exist on the ORM models yet).

- [ ] **Step 3: Add `is_active`/`removed_at` to `JobSource`**

In `backend/jose/models/core.py`, change:

```python
class JobSource(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "job_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", "source_id", name="uq_job_source_link"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    source_job_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

to:

```python
class JobSource(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "job_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", "source_id", name="uq_job_source_link"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    source_job_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Add `reposted_from_job_id` to `Job`**

In the same file, change:

```python
    merged_into_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )

    company: Mapped[Company] = relationship()
```

to:

```python
    merged_into_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    reposted_from_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )

    company: Mapped[Company] = relationship()
```

- [ ] **Step 5: Add `is_material` to `JobVersion`**

In the same file, change:

```python
class JobVersion(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "content_hash", name="uq_job_version_hash"),
        Index("ix_job_versions_job_seen", "job_id", "seen_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
```

to:

```python
class JobVersion(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "content_hash", name="uq_job_version_hash"),
        Index("ix_job_versions_job_seen", "job_id", "seen_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_material: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

- [ ] **Step 6: Write the migration**

Create `backend/alembic/versions/0006_job_change_removal_detection.py`:

```python
"""Add job-source active/removed tracking, job reposts, and material version flag.

Revision ID: 0006_job_change_removal_detection
Revises: 0005_job_merge_candidates
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_job_change_removal_detection"
down_revision = "0005_job_merge_candidates"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "job_sources",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "job_sources", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column("jobs", sa.Column("reposted_from_job_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_jobs_reposted_from_job_id",
        "jobs",
        "jobs",
        ["reposted_from_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_jobs_reposted_from_job_id", "jobs", ["reposted_from_job_id"])

    op.add_column(
        "job_versions",
        sa.Column("is_material", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("job_versions", "is_material")

    op.drop_index("ix_jobs_reposted_from_job_id", table_name="jobs")
    op.drop_constraint("fk_jobs_reposted_from_job_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "reposted_from_job_id")

    op.drop_column("job_sources", "removed_at")
    op.drop_column("job_sources", "is_active")
```

- [ ] **Step 7: Apply the migration and run the tests**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest tests/test_job_change_removal.py -v"`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/jose/models/core.py backend/alembic/versions/0006_job_change_removal_detection.py backend/tests/test_job_change_removal.py
git commit -m "feat: add job-source active/removed state, job repost link, and version material flag"
```

---

## Task 2: `material_hash` utility

**Files:**
- Modify: `backend/jose/collectors/utils.py`
- Test: `backend/tests/test_collectors.py`

**Interfaces:**
- Consumes: `html_to_text`, `normalize_whitespace`, `stable_hash` (already in `utils.py`).
- Produces: `jose.collectors.utils.MATERIAL_SNAPSHOT_FIELDS: tuple[str, ...]` and `jose.collectors.utils.material_hash(snapshot: dict[str, Any]) -> str`. Task 3 imports and calls `material_hash`.

- [ ] **Step 1: Write the failing tests**

Add to the top of `backend/tests/test_collectors.py`, to the existing `from jose.collectors.utils import (...)` block:

```python
from jose.collectors.utils import (
    canonicalize_url,
    fuzzy_match_score,
    job_fingerprint,
    material_hash,
    normalize_title,
)
```

(Keep every name already imported there — only add `material_hash`.)

Append to the end of the file:

```python
def _snapshot(**overrides):
    base = {
        "title": "Software Engineer",
        "location": "San Francisco, CA",
        "remote_type": None,
        "employment_type": "full_time",
        "compensation_min": 150000,
        "compensation_max": 200000,
        "currency": "USD",
        "department": "Engineering",
        "application_url": "https://acme.example.com/apply/1",
        "description_text": None,
        "description_html": "<p>Build great things.</p>",
    }
    base.update(overrides)
    return base


def test_material_hash_ignores_description_markup_only_changes():
    base = _snapshot()
    reformatted = _snapshot(description_html="<div><p>Build   great things.</p></div>")

    assert material_hash(base) == material_hash(reformatted)


def test_material_hash_changes_on_compensation_change():
    base = _snapshot()
    changed = _snapshot(compensation_min=160000)

    assert material_hash(base) != material_hash(changed)


def test_material_hash_changes_on_description_text_change():
    base = _snapshot()
    changed = _snapshot(description_html="<p>Build great things, remotely.</p>")

    assert material_hash(base) != material_hash(changed)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collectors.py -v -k material_hash`
Expected: FAIL — `ImportError: cannot import name 'material_hash' from 'jose.collectors.utils'`

- [ ] **Step 3: Implement `material_hash`**

In `backend/jose/collectors/utils.py`, add `from typing import Any` to the top imports (alongside the existing `import re`, before `from urllib.parse import ...`), then append at the end of the file (after `fuzzy_match_score`):

```python
MATERIAL_SNAPSHOT_FIELDS = (
    "title",
    "location",
    "remote_type",
    "employment_type",
    "compensation_min",
    "compensation_max",
    "currency",
    "department",
    "application_url",
)


def material_hash(snapshot: dict[str, Any]) -> str:
    payload = {key: snapshot.get(key) for key in MATERIAL_SNAPSHOT_FIELDS}
    description_html = snapshot.get("description_html")
    payload["description"] = (
        html_to_text(description_html)
        if description_html
        else normalize_whitespace(snapshot.get("description_text"))
    )
    return stable_hash(payload)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collectors.py -v`
Expected: PASS (all tests in the file, including pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/jose/collectors/utils.py backend/tests/test_collectors.py
git commit -m "feat: add material_hash to distinguish substantive job changes from formatting"
```

---

## Task 3: Tag each `JobVersion` as material or formatting-only

**Files:**
- Modify: `backend/jose/services/collection.py` (imports; `_upsert_job`'s update branch and its `JobVersion` insert)
- Test: `backend/tests/test_job_change_removal.py`

**Interfaces:**
- Consumes: `material_hash` (Task 2).
- Produces: no new public interface — every `JobVersion` row `_upsert_job` writes now carries a correct `is_material` value. Task 6's dashboard query depends on this being correct.

- [ ] **Step 1: Write the failing tests**

Add to the top of `backend/tests/test_job_change_removal.py`:

```python
from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.models import Job, JobSource, JobVersion
from jose.schemas import SourceCreate
from jose.services.collection import collect_source
from jose.services.sources import create_source
```

(`uuid`, `_make_company`, `_make_job` stay imported from Task 1 — add `JobSource` to the existing `from jose.models import ...` line rather than duplicating it.)

Append to the end of the file:

```python
class _FakeCollector:
    def __init__(self, jobs):
        self._jobs = jobs

    def collect(self, source_name, source_url):
        return CollectionResult(jobs=self._jobs)


def _collect(monkeypatch, db_session, source, jobs):
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector(jobs),
    )
    return collect_source(db_session, source.id)


def test_formatting_only_description_change_is_not_material(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-mat.example.com/jobs")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat.example.com/apply/1",
        description_html="<p>Build great things.</p>",
    )
    _collect(monkeypatch, db_session, source, [first])

    reformatted = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat.example.com/apply/1",
        description_html="<div><p>Build   great things.</p></div>",
    )
    _collect(monkeypatch, db_session, source, [reformatted])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    versions = db_session.scalars(
        select(JobVersion).where(JobVersion.job_id == job.id).order_by(JobVersion.seen_at)
    ).all()
    assert len(versions) == 2
    assert versions[1].is_material is False


def test_compensation_change_is_material(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-mat2.example.com/jobs")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat2.example.com/apply/1",
        compensation_min=150000,
    )
    _collect(monkeypatch, db_session, source, [first])

    raised = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat2.example.com/apply/1",
        compensation_min=160000,
    )
    _collect(monkeypatch, db_session, source, [raised])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    versions = db_session.scalars(
        select(JobVersion).where(JobVersion.job_id == job.id).order_by(JobVersion.seen_at)
    ).all()
    assert len(versions) == 2
    assert versions[1].is_material is True


def test_new_job_first_version_is_not_counted_as_a_change(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-mat3.example.com/jobs")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-mat3.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [first])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    version = db_session.scalar(select(JobVersion).where(JobVersion.job_id == job.id))
    assert version.is_material is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_change_removal.py -v -k material`
Expected: FAIL — all three `is_material` assertions fail (every `JobVersion` currently defaults to `True` regardless of what changed, per Task 1's migration default).

- [ ] **Step 3: Wire `material_hash` into `_upsert_job`**

In `backend/jose/services/collection.py`, add `material_hash` to the existing `from jose.collectors.utils import (...)` block:

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
```

Then change:

```python
    created = False
    updated = False
    if not job:
```

to:

```python
    created = False
    updated = False
    version_is_material = False
    if not job:
```

Then, in the `else:` branch (existing job found), change:

```python
    else:
        job.last_seen_at = utcnow()
        job.removed_at = None
        job.status = "active"
        if job.content_hash != content_hash:
            if not matched_via_merge:
```

to:

```python
    else:
        job.last_seen_at = utcnow()
        job.removed_at = None
        job.status = "active"
        if job.content_hash != content_hash:
            previous_version = session.scalar(
                select(JobVersion).where(
                    JobVersion.job_id == job.id, JobVersion.content_hash == job.content_hash
                )
            )
            version_is_material = (
                previous_version is None
                or material_hash(previous_version.snapshot) != material_hash(snapshot)
            )
            if not matched_via_merge:
```

Finally, change the `JobVersion` insert at the bottom of the function:

```python
    version = session.scalar(
        select(JobVersion).where(
            JobVersion.job_id == job.id,
            JobVersion.content_hash == content_hash,
        )
    )
    if not version:
        session.add(
            JobVersion(
                user_id=source.user_id,
                job_id=job.id,
                content_hash=content_hash,
                snapshot=snapshot,
            )
        )
```

to:

```python
    version = session.scalar(
        select(JobVersion).where(
            JobVersion.job_id == job.id,
            JobVersion.content_hash == content_hash,
        )
    )
    if not version:
        session.add(
            JobVersion(
                user_id=source.user_id,
                job_id=job.id,
                content_hash=content_hash,
                snapshot=snapshot,
                is_material=version_is_material,
            )
        )
```

`version_is_material` stays `False` for a brand-new job (initialized before the `if not job:` branch and never touched inside it) — a job's first sighting is a creation event, not a change, so it must never inflate the "changed" count Task 6 adds to the dashboard.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_job_change_removal.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/jose/services/collection.py backend/tests/test_job_change_removal.py
git commit -m "feat: tag job versions as material or formatting-only changes"
```

---

## Task 4: Job-source active/removed sweep and global job removal

**Files:**
- Modify: `backend/jose/services/collection.py` (`collect_source`; `_upsert_job`'s `JobSource` link section; new `_sweep_inactive_job_sources` helper)
- Test: `backend/tests/test_job_change_removal.py`

**Interfaces:**
- Consumes: `JobSource.is_active`/`removed_at` (Task 1).
- Produces: `jose.services.collection._sweep_inactive_job_sources(session, source, run_started_at) -> None` (module-private). After this task, a source's successful run always leaves `JobSource.is_active`/`Job.status` accurate for that source's links.

- [ ] **Step 1: Write the failing tests**

Add `import pytest` to the top of `backend/tests/test_job_change_removal.py` (alongside the
existing `import uuid`) — `test_failed_run_leaves_job_source_state_untouched` below needs it.

Append to the end of the file:

```python
def test_job_source_link_goes_inactive_when_absent_from_next_successful_run(
    db_session, user, monkeypatch
):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-sweep1.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep1.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [job_item])
    _collect(monkeypatch, db_session, source, [])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    link = db_session.scalar(select(JobSource).where(JobSource.job_id == job.id))

    assert link.is_active is False
    assert link.removed_at is not None
    assert job.status == "removed"
    assert job.removed_at is not None


def test_job_stays_active_when_a_second_source_still_lists_it(db_session, user, monkeypatch):
    source_a = create_source(
        db_session, user, SourceCreate(name="Acme A", url="https://acme-sweep2a.example.com/jobs")
    )
    source_b = create_source(
        db_session, user, SourceCreate(name="Acme B", url="https://acme-sweep2b.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep2.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source_a, [job_item])
    _collect(monkeypatch, db_session, source_b, [job_item])

    _collect(monkeypatch, db_session, source_a, [])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert job.status == "active"

    link_a = db_session.scalar(
        select(JobSource).where(JobSource.job_id == job.id, JobSource.source_id == source_a.id)
    )
    link_b = db_session.scalar(
        select(JobSource).where(JobSource.job_id == job.id, JobSource.source_id == source_b.id)
    )
    assert link_a.is_active is False
    assert link_b.is_active is True


def test_failed_run_leaves_job_source_state_untouched(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-sweep3.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep3.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [job_item])

    class _FailingCollector:
        def collect(self, source_name, source_url):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector(),
    )
    with pytest.raises(RuntimeError):
        collect_source(db_session, source.id)

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    link = db_session.scalar(select(JobSource).where(JobSource.job_id == job.id))
    assert job.status == "active"
    assert link.is_active is True


def test_revival_reactivates_job_and_link(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-sweep4.example.com/jobs")
    )
    job_item = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-sweep4.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [job_item])
    _collect(monkeypatch, db_session, source, [])

    job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert job.status == "removed"

    _collect(monkeypatch, db_session, source, [job_item])

    db_session.refresh(job)
    link = db_session.scalar(select(JobSource).where(JobSource.job_id == job.id))
    assert job.status == "active"
    assert job.removed_at is None
    assert link.is_active is True
    assert link.removed_at is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_change_removal.py -v -k "sweep or revival"`
Expected: FAIL — links never go inactive and jobs never reach `status == "removed"` (no sweep exists yet).

- [ ] **Step 3: Set `is_active`/`removed_at` on every touched link**

In `backend/jose/services/collection.py`, in `_upsert_job`, change:

```python
    else:
        link.last_seen_at = utcnow()
        link.source_job_url = item.source_job_url or item.application_url
```

to:

```python
    else:
        link.last_seen_at = utcnow()
        link.source_job_url = item.source_job_url or item.application_url
        link.is_active = True
        link.removed_at = None
```

(The `if not link:` branch that creates a brand-new `JobSource` needs no change — `is_active` already defaults to `True` at the model level.)

- [ ] **Step 4: Add the sweep helper**

In `backend/jose/services/collection.py`, add this function directly after `collect_source` (before `_find_fuzzy_candidate`):

```python
def _sweep_inactive_job_sources(
    session: Session, source: Source, run_started_at: datetime
) -> None:
    stale_links = session.scalars(
        select(JobSource).where(
            JobSource.source_id == source.id,
            JobSource.is_active.is_(True),
            JobSource.last_seen_at < run_started_at,
        )
    ).all()
    affected_job_ids: set[uuid.UUID] = set()
    for link in stale_links:
        link.is_active = False
        link.removed_at = utcnow()
        affected_job_ids.add(link.job_id)

    for job_id in affected_job_ids:
        still_active = session.scalar(
            select(JobSource).where(JobSource.job_id == job_id, JobSource.is_active.is_(True))
        )
        if still_active is None:
            job = session.get(Job, job_id)
            if job is not None and job.status == "active":
                job.status = "removed"
                job.removed_at = utcnow()
```

- [ ] **Step 5: Call the sweep at the end of a successful run**

In `collect_source`, change:

```python
        for item in result.jobs:
            was_created, was_updated = _upsert_job(session, source, item)
            created += int(was_created)
            updated += int(was_updated)

        run = session.get(SourceRun, run.id)
```

to:

```python
        for item in result.jobs:
            was_created, was_updated = _upsert_job(session, source, item)
            created += int(was_created)
            updated += int(was_updated)

        _sweep_inactive_job_sources(session, source, run.started_at)
        session.commit()

        run = session.get(SourceRun, run.id)
```

(`session.commit()` after the sweep is needed because `_upsert_job` already commits per-item, and `run`/`source` are about to be re-fetched via `session.get` immediately after — committing first keeps the sweep's changes durable before that re-fetch, matching the existing pattern of committing before re-fetching in this function.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_job_change_removal.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/jose/services/collection.py backend/tests/test_job_change_removal.py
git commit -m "feat: sweep job-source links inactive and mark jobs globally removed"
```

---

## Task 5: Repost linking against removed jobs

**Files:**
- Modify: `backend/jose/services/collection.py` (`_find_fuzzy_candidate` signature; `_upsert_job`'s create branch)
- Test: `backend/tests/test_job_change_removal.py`

**Interfaces:**
- Consumes: `Job.reposted_from_job_id` (Task 1), `Job.status == "removed"` (Task 4 is what actually produces removed jobs at runtime).
- Produces: no new public interface — `_find_fuzzy_candidate` gains a required `status` parameter; `_upsert_job`'s create branch sets `reposted_from_job_id` when a confident match against a removed job is found.

- [ ] **Step 1: Write the failing tests**

Append to the end of `backend/tests/test_job_change_removal.py` (add `JobMergeCandidate` to the existing `from jose.models import ...` line):

```python
def test_repost_linked_to_removed_job_above_threshold(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-repost1.example.com/jobs")
    )
    original = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://acme-repost1.example.com/apply/1",
        ats_type="greenhouse",
        external_job_id="gh-100",
    )
    _collect(monkeypatch, db_session, source, [original])
    _collect(monkeypatch, db_session, source, [])

    removed_job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert removed_job.status == "removed"

    reposted = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://acme-repost1.example.com/apply/1-repost",
        ats_type="greenhouse",
        external_job_id="gh-200",
    )
    _collect(monkeypatch, db_session, source, [reposted])

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2
    new_job = next(j for j in jobs if j.id != removed_job.id)
    assert new_job.reposted_from_job_id == removed_job.id


def test_repost_not_linked_below_threshold(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-repost2.example.com/jobs")
    )
    original = CollectedJob(
        company_name="Acme",
        title="Backend Engineer",
        location="San Francisco, CA",
        application_url="https://acme-repost2.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [original])
    _collect(monkeypatch, db_session, source, [])

    removed_job = db_session.scalar(select(Job).where(Job.user_id == user.id))
    assert removed_job.status == "removed"

    unrelated = CollectedJob(
        company_name="Acme",
        title="Enterprise Sales Director",
        location="San Francisco, CA",
        application_url="https://acme-repost2.example.com/apply/2",
    )
    _collect(monkeypatch, db_session, source, [unrelated])

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2
    new_job = next(j for j in jobs if j.id != removed_job.id)
    assert new_job.reposted_from_job_id is None


def test_active_fuzzy_match_uses_merge_queue_not_repost_link(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="OpenAI board", url="https://openai-repost-a.example.com")
    )
    first = CollectedJob(
        company_name="OpenAI",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-repost-a.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, source, [first])

    second_source = create_source(
        db_session, user, SourceCreate(name="OpenAI board 2", url="https://openai-repost-b.example.com")
    )
    second = CollectedJob(
        company_name="OpenAI, Inc.",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-repost-b.example.com/apply/1",
    )
    _collect(monkeypatch, db_session, second_source, [second])

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2
    assert all(job.reposted_from_job_id is None for job in jobs)

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert len(candidates) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_change_removal.py -v -k repost`
Expected: FAIL — `test_repost_linked_to_removed_job_above_threshold` fails (`reposted_from_job_id` stays `None`); `test_active_fuzzy_match_uses_merge_queue_not_repost_link` already passes (documents existing Tier-2 behavior) — that is fine, it is a guard-rail test for this task, not a new-behavior test.

- [ ] **Step 3: Generalize `_find_fuzzy_candidate` to take a `status` parameter**

In `backend/jose/services/collection.py`, change:

```python
def _find_fuzzy_candidate(
    session: Session, user_id: uuid.UUID, company_name: str, title: str, location: str | None
) -> tuple[Job, dict[str, float]] | None:
    rows = session.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.user_id == user_id, Job.status == "active")
    ).all()
```

to:

```python
def _find_fuzzy_candidate(
    session: Session,
    user_id: uuid.UUID,
    company_name: str,
    title: str,
    location: str | None,
    status: str,
) -> tuple[Job, dict[str, float]] | None:
    rows = session.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.user_id == user_id, Job.status == status)
    ).all()
```

- [ ] **Step 4: Wire the `status="active"` call site and add the `status="removed"` repost search**

In `_upsert_job`, change:

```python
    created = False
    updated = False
    version_is_material = False
    if not job:
        fuzzy_match = _find_fuzzy_candidate(
            session, source.user_id, company_name, item.title, item.location
        )
        job = Job(
            user_id=source.user_id,
            company_id=company.id,
            title=item.title,
            normalized_title=normalize_title(item.title),
            description_text=item.description_text,
            description_html=item.description_html,
            department=item.department,
            location=item.location,
            remote_type=item.remote_type,
            employment_type=item.employment_type,
            compensation_min=item.compensation_min,
            compensation_max=item.compensation_max,
            currency=item.currency,
            application_url=item.application_url,
            canonical_url=canonical_url,
            ats_type=item.ats_type,
            external_job_id=item.external_job_id,
            published_at=item.published_at,
            fingerprint=fingerprint,
            content_hash=content_hash,
            raw_payload=raw_payload,
        )
        session.add(job)
        session.flush()
        created = True
        if fuzzy_match is not None:
            candidate_job, scores = fuzzy_match
            _flag_fuzzy_duplicate(session, source.user_id, job, candidate_job, scores)
```

to:

```python
    created = False
    updated = False
    version_is_material = False
    if not job:
        fuzzy_match = _find_fuzzy_candidate(
            session, source.user_id, company_name, item.title, item.location, status="active"
        )
        repost_match = (
            None
            if fuzzy_match is not None
            else _find_fuzzy_candidate(
                session, source.user_id, company_name, item.title, item.location, status="removed"
            )
        )
        job = Job(
            user_id=source.user_id,
            company_id=company.id,
            title=item.title,
            normalized_title=normalize_title(item.title),
            description_text=item.description_text,
            description_html=item.description_html,
            department=item.department,
            location=item.location,
            remote_type=item.remote_type,
            employment_type=item.employment_type,
            compensation_min=item.compensation_min,
            compensation_max=item.compensation_max,
            currency=item.currency,
            application_url=item.application_url,
            canonical_url=canonical_url,
            ats_type=item.ats_type,
            external_job_id=item.external_job_id,
            published_at=item.published_at,
            fingerprint=fingerprint,
            content_hash=content_hash,
            raw_payload=raw_payload,
            reposted_from_job_id=repost_match[0].id if repost_match else None,
        )
        session.add(job)
        session.flush()
        created = True
        if fuzzy_match is not None:
            candidate_job, scores = fuzzy_match
            _flag_fuzzy_duplicate(session, source.user_id, job, candidate_job, scores)
```

Repost linking is deliberately auto-applied (no `JobMergeCandidate` row) — unlike merging two currently-visible active duplicates, linking a new job to an already-removed one is purely additive lineage and carries no risk of hiding a live, distinct posting.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_job_change_removal.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/jose/services/collection.py backend/tests/test_job_change_removal.py
git commit -m "feat: auto-link reposted jobs to their prior removed record"
```

---

## Task 6: Dashboard counts and jobs API field

**Files:**
- Modify: `backend/jose/schemas.py` (`DashboardSummary`)
- Modify: `backend/jose/services/dashboard.py` (`get_dashboard_summary`)
- Modify: `backend/jose/api/routes/jobs.py` (`list_jobs` response dict)
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `Job.status == "removed"`, `Job.reposted_from_job_id`, `JobVersion.is_material` (Tasks 1, 3, 4, 5).
- Produces: `DashboardSummary.jobs_new_last_24h`, `.jobs_changed_last_24h`, `.jobs_removed_last_24h`, `.jobs_reposted_last_24h`; `GET /api/v1/jobs` response items gain `"reposted_from_job_id"`. This is the last task — nothing later consumes these.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_jobs_api.py`:

```python
def test_list_jobs_includes_reposted_from_job_id(client, db_session, user):
    company = _make_company(db_session, user)
    original = _make_job(
        db_session, user, company, application_url="https://acme.example.com/1", status="removed"
    )
    repost = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/2",
        reposted_from_job_id=original.id,
    )
    db_session.commit()

    response = client.get("/api/v1/jobs")

    assert response.status_code == 200
    body = {item["id"]: item for item in response.json()}
    assert body[str(repost.id)]["reposted_from_job_id"] == str(original.id)


def test_dashboard_summary_new_changed_removed_reposted_counts(db_session, user):
    from datetime import UTC, datetime

    from jose.models import JobVersion

    company = _make_company(db_session, user)

    _make_job(db_session, user, company, application_url="https://acme.example.com/new")

    changed_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/changed"
    )
    db_session.add(
        JobVersion(
            user_id=user.id,
            job_id=changed_job.id,
            content_hash="hash-changed",
            snapshot={"a": 1},
            is_material=True,
        )
    )

    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/removed",
        status="removed",
        removed_at=datetime.now(UTC),
    )

    original_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/original"
    )
    _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/repost",
        reposted_from_job_id=original_job.id,
    )
    db_session.commit()

    summary = get_dashboard_summary(db_session, user)

    assert summary.jobs_new_last_24h == 5
    assert summary.jobs_changed_last_24h == 1
    assert summary.jobs_removed_last_24h == 1
    assert summary.jobs_reposted_last_24h == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_jobs_api.py -v -k "reposted_from_job_id or new_changed_removed_reposted"`
Expected: FAIL — `KeyError: 'reposted_from_job_id'` on the API test; `AttributeError: 'DashboardSummary' object has no attribute 'jobs_new_last_24h'` on the dashboard test.

- [ ] **Step 3: Add the new `DashboardSummary` fields**

In `backend/jose/schemas.py`, change:

```python
class DashboardSummary(BaseModel):
    sources_total: int
    sources_enabled: int
    sources_failing: int
    jobs_total: int
    jobs_seen_last_24h: int
    queued_tasks: int
    running_tasks: int
```

to:

```python
class DashboardSummary(BaseModel):
    sources_total: int
    sources_enabled: int
    sources_failing: int
    jobs_total: int
    jobs_seen_last_24h: int
    jobs_new_last_24h: int
    jobs_changed_last_24h: int
    jobs_removed_last_24h: int
    jobs_reposted_last_24h: int
    queued_tasks: int
    running_tasks: int
```

- [ ] **Step 4: Compute the new counts in `get_dashboard_summary`**

Replace the full contents of `backend/jose/services/dashboard.py` with:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jose.models import Job, JobVersion, Source, Task, User
from jose.schemas import DashboardSummary


def get_dashboard_summary(session: Session, user: User) -> DashboardSummary:
    since = datetime.now(UTC) - timedelta(hours=24)

    jobs_new = (
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.status != "merged", Job.first_seen_at >= since)
        )
        or 0
    )

    return DashboardSummary(
        sources_total=session.scalar(
            select(func.count()).select_from(Source).where(Source.user_id == user.id)
        )
        or 0,
        sources_enabled=session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.user_id == user.id, Source.enabled.is_(True))
        )
        or 0,
        sources_failing=session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.user_id == user.id, Source.last_error.is_not(None))
        )
        or 0,
        jobs_total=session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.status != "merged")
        )
        or 0,
        jobs_seen_last_24h=jobs_new,
        jobs_new_last_24h=jobs_new,
        jobs_changed_last_24h=session.scalar(
            select(func.count(func.distinct(JobVersion.job_id)))
            .select_from(JobVersion)
            .join(Job, Job.id == JobVersion.job_id)
            .where(
                Job.user_id == user.id,
                JobVersion.is_material.is_(True),
                JobVersion.seen_at >= since,
            )
        )
        or 0,
        jobs_removed_last_24h=session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.status == "removed", Job.removed_at >= since)
        )
        or 0,
        jobs_reposted_last_24h=session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.user_id == user.id,
                Job.reposted_from_job_id.is_not(None),
                Job.first_seen_at >= since,
            )
        )
        or 0,
        queued_tasks=session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user.id, Task.status == "queued")
        )
        or 0,
        running_tasks=session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user.id, Task.status == "running")
        )
        or 0,
    )
```

- [ ] **Step 5: Add `reposted_from_job_id` to the jobs API response**

In `backend/jose/api/routes/jobs.py`, change:

```python
        {
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
        }
```

to:

```python
        {
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
        }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_jobs_api.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend suite and ruff**

Run: `docker compose run --rm api sh -c "pytest -v && ruff check ."`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/jose/schemas.py backend/jose/services/dashboard.py backend/jose/api/routes/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: surface new/changed/removed/reposted counts on the dashboard"
```

---

## Out of scope (per approved design)

- A dedicated removed/changed/reposted review UI beyond the existing Jobs page and dashboard counts — Issue 11's broader jobs-review workspace.
- AI/embedding-based description-change classification.
- A grace period / multi-run confirmation before marking a link removed.
- Notifications (email/etc.) on removal or repost.
