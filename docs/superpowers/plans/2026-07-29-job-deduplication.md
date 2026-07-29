# Job Deduplication (Issue 07) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the same job found through different sources per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 07 and `docs/superpowers/specs/2026-07-29-job-deduplication-design.md`.

**Architecture:** `_upsert_job` in `backend/jose/services/collection.py` gains two new matching tiers above today's exact-fingerprint match: an ATS-job-ID tier that auto-merges regardless of text differences, and a `difflib`-based fuzzy-text tier that never auto-merges but flags a `JobMergeCandidate` row for manual review. A new `backend/jose/services/job_merge.py` service resolves those candidates (merge or dismiss) and can undo a merge, writing a `SystemEvent` audit row each time. A minimal `/jobs/review` web page exposes the queue.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, pytest, Next.js App Router, TypeScript. All backend commands run via `docker compose run --rm api ...`; frontend via `docker compose run --rm web ...` (Colima-backed Docker per `[[docker_environment_colima]]`).

## Global Constraints

- Never invent career facts, dates, metrics, titles, employers, compensation, or personal information — unknown stays unknown (CLAUDE.md rule #3/#4).
- A failed collector is a failure, never a successful zero-result run (CLAUDE.md rule #5) — nothing in this plan changes collector error handling; dedup logic only runs after a collector has already succeeded.
- Apply deterministic filters before paid AI calls (CLAUDE.md rule #6) — fuzzy matching uses stdlib `difflib` only, no AI/embedding calls, per the approved spec's explicit decision.
- Every user-owned record includes `user_id`; use timezone-aware UTC datetimes; use UUID primary keys (CLAUDE.md architecture rules).
- Do not put business logic in route handlers — merge/unmerge/dismiss logic lives in `jose/services/job_merge.py`, routes stay thin.
- Add a migration whenever the persisted schema changes (CLAUDE.md working rule).
- Use fixtures for collector/service tests. No live network calls in unit tests.
- Ruff must pass (line length 100, rules E/F/I/B/UP/SIM per `backend/pyproject.toml`). Next.js `eslint`/`tsc --noEmit`/`next build` must pass for web changes.
- Definition of done: acceptance criteria met, unit tests pass, ruff passes, migrations included, error paths handled, no unsupported claim or hidden automation introduced.

---

## Task 1: Data model — `Job.merged_into_job_id` and `JobMergeCandidate`

**Files:**
- Modify: `backend/jose/models/core.py:5-13` (import), `:136` (Job column), `:170` (new class insertion point)
- Modify: `backend/jose/models/__init__.py`
- Create: `backend/alembic/versions/0005_job_merge_candidates.py`
- Test: `backend/tests/test_job_dedup.py` (new file)

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first task).
- Produces: `jose.models.Job.merged_into_job_id: uuid.UUID | None`. `jose.models.JobMergeCandidate` with fields `id, user_id, job_id, candidate_job_id, similarity_score: float, matched_signals: dict, status: str, resolved_at: datetime | None, kept_job_id: uuid.UUID | None, merged_job_id: uuid.UUID | None, moved_job_source_ids: list[str], moved_job_version_ids: list[str]`. Every later task imports `JobMergeCandidate` from `jose.models`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_job_dedup.py`:

```python
import uuid

from jose.models import Company, Job, JobMergeCandidate


def _make_company(session, user, name="Acme"):
    company = Company(user_id=user.id, name=name, normalized_name=name.lower())
    session.add(company)
    session.flush()
    return company


def _make_job(session, user, company, **overrides):
    defaults = dict(
        user_id=user.id,
        company_id=company.id,
        title="Software Engineer",
        normalized_title="software engineer",
        location="San Francisco, CA",
        application_url="https://acme.example.com/jobs/1",
        canonical_url="https://acme.example.com/jobs/1",
        fingerprint=uuid.uuid4().hex,
        content_hash=uuid.uuid4().hex,
    )
    defaults.update(overrides)
    job = Job(**defaults)
    session.add(job)
    session.flush()
    return job


def test_job_merged_into_job_id_defaults_to_none(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    db_session.commit()

    assert job.merged_into_job_id is None
    assert job.status == "active"


def test_job_merge_candidate_persists_fields(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company, application_url="https://acme.example.com/jobs/1")
    candidate_job = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/jobs/2",
        fingerprint=uuid.uuid4().hex,
    )

    candidate = JobMergeCandidate(
        user_id=user.id,
        job_id=job.id,
        candidate_job_id=candidate_job.id,
        similarity_score=0.9,
        matched_signals={"company": 1.0, "title": 1.0, "location": 0.5},
        status="pending",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    assert candidate.id is not None
    assert candidate.status == "pending"
    assert candidate.resolved_at is None
    assert candidate.matched_signals == {"company": 1.0, "title": 1.0, "location": 0.5}
    assert candidate.moved_job_source_ids == []
    assert candidate.moved_job_version_ids == []
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_dedup.py -v`
Expected: FAIL — `ImportError: cannot import name 'JobMergeCandidate' from 'jose.models'`

- [ ] **Step 3: Add the `merged_into_job_id` column to `Job`**

In `backend/jose/models/core.py`, add `Float` to the existing `sqlalchemy` import block (around line 5-13) so it reads:

```python
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
```

Then, in the `Job` class, change:

```python
    fingerprint: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    company: Mapped[Company] = relationship()
```

to:

```python
    fingerprint: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    merged_into_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )

    company: Mapped[Company] = relationship()
```

- [ ] **Step 4: Add the `JobMergeCandidate` model**

In `backend/jose/models/core.py`, immediately after the `JobVersion` class (after its `snapshot` column, before the blank lines leading into `class Task`), insert:

```python
class JobMergeCandidate(UUIDPrimaryKeyMixin, TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "job_merge_candidates"
    __table_args__ = (Index("ix_job_merge_candidates_user_status", "user_id", "status"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    candidate_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    similarity_score: Mapped[float] = mapped_column(Float)
    matched_signals: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kept_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    merged_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    moved_job_source_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    moved_job_version_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
```

- [ ] **Step 5: Export `JobMergeCandidate` from the models package**

In `backend/jose/models/__init__.py`, add it to both the import and `__all__`:

```python
from jose.models.core import (
    Company,
    Job,
    JobMergeCandidate,
    JobSource,
    JobVersion,
    Source,
    SourceImportRun,
    SourceRun,
    SystemEvent,
    Task,
    User,
)

__all__ = [
    "Company",
    "Job",
    "JobMergeCandidate",
    "JobSource",
    "JobVersion",
    "Source",
    "SourceImportRun",
    "SourceRun",
    "SystemEvent",
    "Task",
    "User",
]
```

- [ ] **Step 6: Write the migration**

Create `backend/alembic/versions/0005_job_merge_candidates.py`:

```python
"""Add job merge candidates table and merged_into_job_id column.

Revision ID: 0005_job_merge_candidates
Revises: 0004_source_platform_detection
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_job_merge_candidates"
down_revision = "0004_source_platform_detection"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("jobs", sa.Column("merged_into_job_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_jobs_merged_into_job_id",
        "jobs",
        "jobs",
        ["merged_into_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_jobs_merged_into_job_id", "jobs", ["merged_into_job_id"])

    op.create_table(
        "job_merge_candidates",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("candidate_job_id", UUID, nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("matched_signals", JSONB, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kept_job_id", UUID, nullable=True),
        sa.Column("merged_job_id", UUID, nullable=True),
        sa.Column("moved_job_source_ids", JSONB, nullable=False),
        sa.Column("moved_job_version_ids", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kept_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merged_job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_merge_candidates_user_id", "job_merge_candidates", ["user_id"])
    op.create_index("ix_job_merge_candidates_job_id", "job_merge_candidates", ["job_id"])
    op.create_index(
        "ix_job_merge_candidates_candidate_job_id", "job_merge_candidates", ["candidate_job_id"]
    )
    op.create_index(
        "ix_job_merge_candidates_user_status", "job_merge_candidates", ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_merge_candidates_user_status", table_name="job_merge_candidates")
    op.drop_index("ix_job_merge_candidates_candidate_job_id", table_name="job_merge_candidates")
    op.drop_index("ix_job_merge_candidates_job_id", table_name="job_merge_candidates")
    op.drop_index("ix_job_merge_candidates_user_id", table_name="job_merge_candidates")
    op.drop_table("job_merge_candidates")
    op.drop_index("ix_jobs_merged_into_job_id", table_name="jobs")
    op.drop_constraint("fk_jobs_merged_into_job_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "merged_into_job_id")
```

- [ ] **Step 7: Apply the migration and run the tests**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest tests/test_job_dedup.py -v"`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/jose/models/core.py backend/jose/models/__init__.py backend/alembic/versions/0005_job_merge_candidates.py backend/tests/test_job_dedup.py
git commit -m "feat: add job_merge_candidates table and Job.merged_into_job_id"
```

---

## Task 2: Fuzzy-match scoring utility

**Files:**
- Modify: `backend/jose/collectors/utils.py`
- Test: `backend/tests/test_collectors.py`

**Interfaces:**
- Consumes: `normalize_name`, `normalize_title` (already in `utils.py`).
- Produces: `jose.collectors.utils.fuzzy_match_score(company_a, title_a, location_a, company_b, title_b, location_b) -> dict[str, float]` returning keys `company`, `title`, `location`, `composite`. `jose.collectors.utils.COMPANY_ALIAS_THRESHOLD = 0.6`, `jose.collectors.utils.FUZZY_MATCH_THRESHOLD = 0.80`. Task 4 imports both the function and both constants.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_collectors.py` (add the new names to the existing `from jose.collectors.utils import (...)` line at the top of the file):

```python
from jose.collectors.utils import (
    COMPANY_ALIAS_THRESHOLD,
    FUZZY_MATCH_THRESHOLD,
    canonicalize_url,
    fuzzy_match_score,
    job_fingerprint,
    normalize_title,
)


def test_fuzzy_match_score_company_alias_clears_threshold():
    scores = fuzzy_match_score(
        "OpenAI",
        "Software Engineer",
        "San Francisco, CA",
        "OpenAI, Inc.",
        "Software Engineer",
        "San Francisco, CA",
    )
    assert scores["company"] >= COMPANY_ALIAS_THRESHOLD
    assert scores["composite"] >= FUZZY_MATCH_THRESHOLD


def test_fuzzy_match_score_location_wording_clears_threshold():
    scores = fuzzy_match_score(
        "Acme", "Software Engineer", "San Francisco, CA",
        "Acme", "Software Engineer", "SF, CA, US",
    )
    assert scores["composite"] >= FUZZY_MATCH_THRESHOLD


def test_fuzzy_match_score_different_role_stays_below_threshold():
    scores = fuzzy_match_score(
        "Acme", "Backend Engineer", "San Francisco, CA",
        "Acme", "Enterprise Sales Director", "San Francisco, CA",
    )
    assert scores["composite"] < FUZZY_MATCH_THRESHOLD


def test_fuzzy_match_score_unrelated_company_fails_prefilter():
    scores = fuzzy_match_score(
        "Acme Robotics", "Software Engineer", "San Francisco, CA",
        "Zephyr Logistics", "Warehouse Associate", "Austin, TX",
    )
    assert scores["company"] < COMPANY_ALIAS_THRESHOLD
```

These thresholds and example pairs were verified against the real `difflib` output before writing this plan (not guessed): the alias pair scores `company=0.750`, `composite=0.875`; the location-wording pair scores `composite=0.942`; the different-role pair scores `composite=0.790`; the unrelated-company pair scores `company=0.483`.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_collectors.py -v -k fuzzy_match_score`
Expected: FAIL — `ImportError: cannot import name 'fuzzy_match_score' from 'jose.collectors.utils'`

- [ ] **Step 3: Implement `fuzzy_match_score`**

In `backend/jose/collectors/utils.py`, add `import difflib` to the top imports (alongside the existing `import hashlib`), then append at the end of the file (after `job_fingerprint`):

```python
COMPANY_ALIAS_THRESHOLD = 0.6
FUZZY_MATCH_THRESHOLD = 0.80


def fuzzy_match_score(
    company_a: str,
    title_a: str,
    location_a: str,
    company_b: str,
    title_b: str,
    location_b: str,
) -> dict[str, float]:
    company = difflib.SequenceMatcher(
        None, normalize_name(company_a), normalize_name(company_b)
    ).ratio()
    title = difflib.SequenceMatcher(
        None, normalize_title(title_a), normalize_title(title_b)
    ).ratio()
    location = difflib.SequenceMatcher(
        None, normalize_name(location_a), normalize_name(location_b)
    ).ratio()
    composite = 0.5 * company + 0.4 * title + 0.1 * location
    return {"company": company, "title": title, "location": location, "composite": composite}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_collectors.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/jose/collectors/utils.py backend/tests/test_collectors.py
git commit -m "feat: add difflib-based fuzzy match scoring for job dedup"
```

---

## Task 3: Tier 1 — ATS job ID auto-merge

**Files:**
- Modify: `backend/jose/services/collection.py:127-129` (the fingerprint lookup in `_upsert_job`)
- Test: `backend/tests/test_job_dedup.py`

**Interfaces:**
- Consumes: nothing new — operates on the existing `Job` fields (`ats_type`, `external_job_id`, `status`).
- Produces: no new public interface; `_upsert_job` now also matches on ATS identity. Task 4 builds on this same function.

- [ ] **Step 1: Write the failing test**

First, update the import block at the top of `backend/tests/test_job_dedup.py` — change:

```python
import uuid

from jose.models import Company, Job, JobMergeCandidate
```

to:

```python
import uuid

from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.models import Company, Job, JobMergeCandidate
from jose.schemas import SourceCreate
from jose.services.collection import collect_source
from jose.services.sources import create_source
```

Then add the fake collector and the test to the end of `backend/tests/test_job_dedup.py`:

```python
class _FakeCollector:
    def __init__(self, jobs):
        self._jobs = jobs

    def collect(self, source_name, source_url):
        return CollectionResult(jobs=self._jobs)


def test_ats_job_id_match_updates_same_job_despite_title_change(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-ats.example.com/jobs")
    )
    first_job = CollectedJob(
        company_name="Acme",
        title="Software Engineer",
        application_url="https://acme-ats.example.com/apply/1",
        ats_type="greenhouse",
        external_job_id="gh-42",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([first_job]),
    )
    collect_source(db_session, source.id)

    retitled_job = CollectedJob(
        company_name="Acme",
        title="Senior Software Engineer",
        application_url="https://acme-ats.example.com/apply/1-v2",
        ats_type="greenhouse",
        external_job_id="gh-42",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([retitled_job]),
    )
    collect_source(db_session, source.id)

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 1
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].external_job_id == "gh-42"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_job_dedup.py -v -k ats_job_id`
Expected: FAIL — two `Job` rows exist instead of one (`assert len(jobs) == 1` fails with `len(jobs) == 2`)

- [ ] **Step 3: Add the Tier 1 lookup**

In `backend/jose/services/collection.py`, change:

```python
    job = session.scalar(
        select(Job).where(Job.user_id == source.user_id, Job.fingerprint == fingerprint)
    )
    created = False
    updated = False
    if not job:
```

to:

```python
    job = session.scalar(
        select(Job).where(Job.user_id == source.user_id, Job.fingerprint == fingerprint)
    )
    if not job and item.ats_type and item.external_job_id:
        job = session.scalar(
            select(Job).where(
                Job.user_id == source.user_id,
                Job.ats_type == item.ats_type,
                Job.external_job_id == item.external_job_id,
                Job.status == "active",
            )
        )
    created = False
    updated = False
    if not job:
```

Then, in the same function's update branch, find:

```python
        if job.content_hash != content_hash:
            job.company_id = company.id
            job.title = item.title
```

and add a fingerprint refresh as the first line inside that block, so it reads:

```python
        if job.content_hash != content_hash:
            job.fingerprint = fingerprint
            job.company_id = company.id
            job.title = item.title
```

This line is a no-op for a Tier 0 exact-fingerprint match (the job was already found by this exact fingerprint) and is what makes a Tier 1 ATS-ID match correct (the job was found by ATS identity, not fingerprint, so its stored fingerprint must be refreshed to match the new title/location/company text).

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm api pytest tests/test_job_dedup.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS (all existing tests plus the new one)

- [ ] **Step 6: Commit**

```bash
git add backend/jose/services/collection.py backend/tests/test_job_dedup.py
git commit -m "feat: auto-merge jobs on matching ATS type and external job id"
```

---

## Task 4: Tier 2 — fuzzy match creates a review-queue candidate

**Files:**
- Modify: `backend/jose/services/collection.py`
- Test: `backend/tests/test_job_dedup.py`

**Interfaces:**
- Consumes: `fuzzy_match_score`, `COMPANY_ALIAS_THRESHOLD`, `FUZZY_MATCH_THRESHOLD` (Task 2). `JobMergeCandidate` (Task 1).
- Produces: `_find_fuzzy_candidate(session, user_id, company_name, title, location) -> tuple[Job, dict[str, float]] | None` and `_flag_fuzzy_duplicate(session, user_id, new_job, candidate_job, scores) -> JobMergeCandidate | None`, both module-private in `jose.services.collection`. Task 5 does not call these directly (it works on `JobMergeCandidate` rows already created) but Task 6's API tests rely on candidates this task creates existing in the database.

- [ ] **Step 1: Write the failing tests**

`JobMergeCandidate`, `select`, `CollectedJob`, `SourceCreate`, `collect_source`, `create_source`,
and `_FakeCollector` are all already imported/defined in `backend/tests/test_job_dedup.py` from
Tasks 1 and 3 — no import changes needed here. Add to the end of the file:

```python
def test_fuzzy_company_alias_creates_pending_merge_candidate(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="OpenAI board", url="https://openai-a.example.com")
    )
    first = CollectedJob(
        company_name="OpenAI",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-a.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([first]),
    )
    collect_source(db_session, source.id)

    second_source = create_source(
        db_session, user, SourceCreate(name="OpenAI board 2", url="https://openai-b.example.com")
    )
    second = CollectedJob(
        company_name="OpenAI, Inc.",
        title="Software Engineer",
        location="San Francisco, CA",
        application_url="https://openai-b.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([second]),
    )
    collect_source(db_session, second_source.id)

    jobs = db_session.scalars(select(Job).where(Job.user_id == user.id)).all()
    assert len(jobs) == 2

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert len(candidates) == 1
    assert candidates[0].status == "pending"
    assert candidates[0].matched_signals["company"] >= 0.6


def test_fuzzy_match_below_threshold_creates_no_candidate(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Acme board", url="https://acme-a.example.com")
    )
    first = CollectedJob(
        company_name="Acme",
        title="Backend Engineer",
        location="San Francisco, CA",
        application_url="https://acme-a.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([first]),
    )
    collect_source(db_session, source.id)

    second_source = create_source(
        db_session, user, SourceCreate(name="Acme board 2", url="https://acme-b.example.com")
    )
    second = CollectedJob(
        company_name="Acme",
        title="Enterprise Sales Director",
        location="San Francisco, CA",
        application_url="https://acme-b.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([second]),
    )
    collect_source(db_session, second_source.id)

    candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert candidates == []


def test_dismissed_pair_is_not_reproposed(db_session, user):
    from jose.services.collection import _flag_fuzzy_duplicate

    company = _make_company(db_session, user, name="Acme")
    job_a = _make_job(db_session, user, company, application_url="https://acme.example.com/a")
    job_b = _make_job(
        db_session,
        user,
        company,
        application_url="https://acme.example.com/b",
        fingerprint=uuid.uuid4().hex,
    )
    scores = {"company": 1.0, "title": 1.0, "location": 1.0, "composite": 1.0}

    first_candidate = _flag_fuzzy_duplicate(db_session, user.id, job_b, job_a, scores)
    db_session.commit()
    assert first_candidate is not None

    first_candidate.status = "dismissed"
    db_session.commit()

    second_candidate = _flag_fuzzy_duplicate(db_session, user.id, job_b, job_a, scores)
    db_session.commit()
    assert second_candidate is None

    all_candidates = db_session.scalars(
        select(JobMergeCandidate).where(JobMergeCandidate.user_id == user.id)
    ).all()
    assert len(all_candidates) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_dedup.py -v -k "fuzzy or dismissed_pair"`
Expected: FAIL — `ImportError: cannot import name '_flag_fuzzy_duplicate'` (and the other two tests fail on `assert len(candidates) == 1` / `assert candidates == []` since no candidates are created yet at all)

- [ ] **Step 3: Implement the fuzzy-candidate search and flagging helpers**

In `backend/jose/services/collection.py`, update the imports at the top of the file:

```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from jose.collectors import get_collector
from jose.collectors.base import CollectedJob
from jose.collectors.utils import (
    COMPANY_ALIAS_THRESHOLD,
    FUZZY_MATCH_THRESHOLD,
    canonicalize_url,
    fuzzy_match_score,
    job_fingerprint,
    normalize_name,
    normalize_title,
    stable_hash,
)
from jose.config import get_settings
from jose.models import Company, Job, JobMergeCandidate, JobSource, JobVersion, Source, SourceRun
```

Then add these two functions right before `_upsert_job`:

```python
def _find_fuzzy_candidate(
    session: Session, user_id: uuid.UUID, company_name: str, title: str, location: str | None
) -> tuple[Job, dict[str, float]] | None:
    rows = session.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.user_id == user_id, Job.status == "active")
    ).all()
    best: tuple[Job, dict[str, float]] | None = None
    for candidate_job, candidate_company_name in rows:
        scores = fuzzy_match_score(
            company_name,
            title,
            location or "",
            candidate_company_name,
            candidate_job.title,
            candidate_job.location or "",
        )
        if scores["company"] < COMPANY_ALIAS_THRESHOLD:
            continue
        if scores["composite"] < FUZZY_MATCH_THRESHOLD:
            continue
        if best is None or scores["composite"] > best[1]["composite"]:
            best = (candidate_job, scores)
    return best


def _flag_fuzzy_duplicate(
    session: Session,
    user_id: uuid.UUID,
    new_job: Job,
    candidate_job: Job,
    scores: dict[str, float],
) -> JobMergeCandidate | None:
    existing = session.scalar(
        select(JobMergeCandidate).where(
            JobMergeCandidate.user_id == user_id,
            JobMergeCandidate.status != "pending",
            or_(
                and_(
                    JobMergeCandidate.job_id == new_job.id,
                    JobMergeCandidate.candidate_job_id == candidate_job.id,
                ),
                and_(
                    JobMergeCandidate.job_id == candidate_job.id,
                    JobMergeCandidate.candidate_job_id == new_job.id,
                ),
            ),
        )
    )
    if existing:
        return None
    merge_candidate = JobMergeCandidate(
        user_id=user_id,
        job_id=new_job.id,
        candidate_job_id=candidate_job.id,
        similarity_score=scores["composite"],
        matched_signals={
            "company": scores["company"],
            "title": scores["title"],
            "location": scores["location"],
        },
        status="pending",
    )
    session.add(merge_candidate)
    return merge_candidate
```

Finally, wire the search into the create branch of `_upsert_job`. Change:

```python
    created = False
    updated = False
    if not job:
        job = Job(
            user_id=source.user_id,
            company_id=company.id,
```

to:

```python
    created = False
    updated = False
    if not job:
        fuzzy_match = _find_fuzzy_candidate(
            session, source.user_id, company_name, item.title, item.location
        )
        job = Job(
            user_id=source.user_id,
            company_id=company.id,
```

and, immediately after the existing `session.flush()` / `created = True` lines that follow the `Job(...)` construction in that same branch, add the flagging call:

```python
        session.add(job)
        session.flush()
        created = True
        if fuzzy_match is not None:
            candidate_job, scores = fuzzy_match
            _flag_fuzzy_duplicate(session, source.user_id, job, candidate_job, scores)
```

(This replaces the existing `session.add(job)` / `session.flush()` / `created = True` three lines — same three lines, with the new `if fuzzy_match is not None:` block appended directly after.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_job_dedup.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

If any threshold-related assertion is off by a small margin due to floating-point differences from the hand-verified values in Task 2, adjust `COMPANY_ALIAS_THRESHOLD`/`FUZZY_MATCH_THRESHOLD` in `utils.py`, not the test expectations — the design spec explicitly treats these as tunable starting points.

- [ ] **Step 6: Commit**

```bash
git add backend/jose/services/collection.py backend/tests/test_job_dedup.py
git commit -m "feat: flag fuzzy job duplicates for review instead of auto-merging"
```

---

## Task 5: Merge/unmerge service with audit trail

**Files:**
- Create: `backend/jose/services/job_merge.py`
- Test: `backend/tests/test_job_merge_service.py` (new file)

**Interfaces:**
- Consumes: `JobMergeCandidate`, `Job`, `JobSource`, `JobVersion`, `SystemEvent`, `User` (from `jose.models`).
- Produces: `jose.services.job_merge.list_merge_candidates(session, user, status="pending") -> list[JobMergeCandidate]`, `dismiss_merge_candidate(session, user, candidate_id) -> JobMergeCandidate`, `merge_candidate(session, user, candidate_id, keep: Literal["job", "candidate"]) -> JobMergeCandidate`, `unmerge_candidate(session, user, candidate_id) -> JobMergeCandidate`, and exceptions `MergeCandidateNotFoundError`, `MergeCandidateNotPendingError`, `MergeCandidateNotMergedError`. Task 6 (API routes) calls all four functions and catches all three exceptions by name.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_job_merge_service.py`:

```python
import uuid

import pytest
from sqlalchemy import select

from jose.models import Company, Job, JobMergeCandidate, JobSource, JobVersion, SystemEvent
from jose.services.job_merge import (
    MergeCandidateNotFoundError,
    MergeCandidateNotMergedError,
    MergeCandidateNotPendingError,
    dismiss_merge_candidate,
    list_merge_candidates,
    merge_candidate,
    unmerge_candidate,
)


def _make_company(session, user, name="Acme"):
    company = Company(user_id=user.id, name=name, normalized_name=name.lower())
    session.add(company)
    session.flush()
    return company


def _make_job(session, user, company, **overrides):
    defaults = dict(
        user_id=user.id,
        company_id=company.id,
        title="Software Engineer",
        normalized_title="software engineer",
        location="San Francisco, CA",
        application_url="https://acme.example.com/jobs/1",
        canonical_url="https://acme.example.com/jobs/1",
        fingerprint=uuid.uuid4().hex,
        content_hash=uuid.uuid4().hex,
    )
    defaults.update(overrides)
    job = Job(**defaults)
    session.add(job)
    session.flush()
    return job


def _make_candidate(session, user, job, candidate_job, **overrides):
    defaults = dict(
        user_id=user.id,
        job_id=job.id,
        candidate_job_id=candidate_job.id,
        similarity_score=0.9,
        matched_signals={"company": 1.0, "title": 1.0, "location": 1.0},
        status="pending",
    )
    defaults.update(overrides)
    candidate = JobMergeCandidate(**defaults)
    session.add(candidate)
    session.flush()
    return candidate


def test_list_merge_candidates_filters_by_status_and_user(db_session, user, other_user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other_job = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    _make_candidate(db_session, user, job, other_job)

    other_company = _make_company(db_session, other_user, name="Other Co")
    other_user_job = _make_job(db_session, other_user, other_company)
    other_user_job_2 = _make_job(
        db_session, other_user, other_company, application_url="https://other.example.com/2"
    )
    _make_candidate(db_session, other_user, other_user_job, other_user_job_2)
    db_session.commit()

    results = list_merge_candidates(db_session, user)
    assert len(results) == 1
    assert results[0].user_id == user.id


def test_dismiss_merge_candidate_marks_dismissed(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    result = dismiss_merge_candidate(db_session, user, candidate.id)

    assert result.status == "dismissed"
    assert result.resolved_at is not None


def test_dismiss_already_resolved_candidate_raises(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other, status="dismissed")
    db_session.commit()

    with pytest.raises(MergeCandidateNotPendingError):
        dismiss_merge_candidate(db_session, user, candidate.id)


def test_merge_candidate_unknown_id_raises(db_session, user):
    with pytest.raises(MergeCandidateNotFoundError):
        dismiss_merge_candidate(db_session, user, uuid.uuid4())


def test_merge_reassigns_job_sources_and_versions(db_session, user):
    company = _make_company(db_session, user)
    kept_job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    merged_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/2"
    )

    merged_source_link = JobSource(
        user_id=user.id, job_id=merged_job.id, source_id=uuid.uuid4(), source_job_url="x"
    )
    merged_version = JobVersion(
        user_id=user.id, job_id=merged_job.id, content_hash="hash-1", snapshot={"a": 1}
    )
    db_session.add_all([merged_source_link, merged_version])
    candidate = _make_candidate(db_session, user, kept_job, merged_job)
    db_session.commit()

    result = merge_candidate(db_session, user, candidate.id, keep="job")

    assert result.status == "merged"
    assert result.kept_job_id == kept_job.id
    assert result.merged_job_id == merged_job.id

    db_session.refresh(merged_job)
    assert merged_job.status == "merged"
    assert merged_job.merged_into_job_id == kept_job.id

    db_session.refresh(merged_source_link)
    assert merged_source_link.job_id == kept_job.id
    db_session.refresh(merged_version)
    assert merged_version.job_id == kept_job.id

    events = db_session.scalars(
        select(SystemEvent).where(SystemEvent.event_type == "job_merged")
    ).all()
    assert len(events) == 1
    assert events[0].entity_id == kept_job.id


def test_merge_link_collision_keeps_more_recently_seen(db_session, user):
    from datetime import UTC, datetime, timedelta

    company = _make_company(db_session, user)
    kept_job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    merged_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/2"
    )
    shared_source_id = uuid.uuid4()
    now = datetime.now(UTC)

    kept_link = JobSource(
        user_id=user.id,
        job_id=kept_job.id,
        source_id=shared_source_id,
        source_job_url="old",
        last_seen_at=now - timedelta(days=1),
    )
    merged_link = JobSource(
        user_id=user.id,
        job_id=merged_job.id,
        source_id=shared_source_id,
        source_job_url="new",
        last_seen_at=now,
    )
    db_session.add_all([kept_link, merged_link])
    candidate = _make_candidate(db_session, user, kept_job, merged_job)
    db_session.commit()

    merge_candidate(db_session, user, candidate.id, keep="job")

    links = db_session.scalars(
        select(JobSource).where(
            JobSource.user_id == user.id, JobSource.source_id == shared_source_id
        )
    ).all()
    assert len(links) == 1
    assert links[0].job_id == kept_job.id
    assert links[0].source_job_url == "new"


def test_unmerge_restores_only_originally_moved_rows(db_session, user):
    company = _make_company(db_session, user)
    kept_job = _make_job(db_session, user, company, application_url="https://acme.example.com/1")
    merged_job = _make_job(
        db_session, user, company, application_url="https://acme.example.com/2"
    )
    original_link = JobSource(
        user_id=user.id, job_id=merged_job.id, source_id=uuid.uuid4(), source_job_url="original"
    )
    db_session.add(original_link)
    candidate = _make_candidate(db_session, user, kept_job, merged_job)
    db_session.commit()

    merge_candidate(db_session, user, candidate.id, keep="job")

    later_link = JobSource(
        user_id=user.id, job_id=kept_job.id, source_id=uuid.uuid4(), source_job_url="later"
    )
    db_session.add(later_link)
    db_session.commit()

    result = unmerge_candidate(db_session, user, candidate.id)

    assert result.status == "dismissed"
    db_session.refresh(merged_job)
    assert merged_job.status == "active"
    assert merged_job.merged_into_job_id is None

    db_session.refresh(original_link)
    assert original_link.job_id == merged_job.id
    db_session.refresh(later_link)
    assert later_link.job_id == kept_job.id

    events = db_session.scalars(
        select(SystemEvent).where(SystemEvent.event_type == "job_unmerged")
    ).all()
    assert len(events) == 1


def test_unmerge_requires_merged_status(db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    with pytest.raises(MergeCandidateNotMergedError):
        unmerge_candidate(db_session, user, candidate.id)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_merge_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jose.services.job_merge'`

- [ ] **Step 3: Implement `jose/services/job_merge.py`**

Create `backend/jose/services/job_merge.py`:

```python
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from jose.models import Job, JobMergeCandidate, JobSource, JobVersion, SystemEvent, User


def utcnow() -> datetime:
    return datetime.now(UTC)


class MergeCandidateNotFoundError(Exception):
    pass


class MergeCandidateNotPendingError(Exception):
    pass


class MergeCandidateNotMergedError(Exception):
    pass


def list_merge_candidates(
    session: Session, user: User, status: str = "pending"
) -> list[JobMergeCandidate]:
    return list(
        session.scalars(
            select(JobMergeCandidate)
            .where(JobMergeCandidate.user_id == user.id, JobMergeCandidate.status == status)
            .order_by(JobMergeCandidate.created_at)
        ).all()
    )


def _get_candidate(session: Session, user: User, candidate_id: uuid.UUID) -> JobMergeCandidate:
    candidate = session.scalar(
        select(JobMergeCandidate).where(
            JobMergeCandidate.id == candidate_id, JobMergeCandidate.user_id == user.id
        )
    )
    if not candidate:
        raise MergeCandidateNotFoundError(str(candidate_id))
    return candidate


def dismiss_merge_candidate(
    session: Session, user: User, candidate_id: uuid.UUID
) -> JobMergeCandidate:
    candidate = _get_candidate(session, user, candidate_id)
    if candidate.status != "pending":
        raise MergeCandidateNotPendingError(str(candidate_id))
    candidate.status = "dismissed"
    candidate.resolved_at = utcnow()
    session.commit()
    session.refresh(candidate)
    return candidate


def merge_candidate(
    session: Session, user: User, candidate_id: uuid.UUID, keep: Literal["job", "candidate"]
) -> JobMergeCandidate:
    candidate = _get_candidate(session, user, candidate_id)
    if candidate.status != "pending":
        raise MergeCandidateNotPendingError(str(candidate_id))

    kept_job_id = candidate.job_id if keep == "job" else candidate.candidate_job_id
    merged_job_id = candidate.candidate_job_id if keep == "job" else candidate.job_id
    merged_job = session.get(Job, merged_job_id)
    assert merged_job is not None

    moved_source_ids: list[str] = []
    for link in session.scalars(
        select(JobSource).where(JobSource.job_id == merged_job_id, JobSource.user_id == user.id)
    ).all():
        existing_link = session.scalar(
            select(JobSource).where(
                JobSource.job_id == kept_job_id,
                JobSource.source_id == link.source_id,
                JobSource.user_id == user.id,
            )
        )
        if existing_link is None:
            link.job_id = kept_job_id
            moved_source_ids.append(str(link.id))
        elif link.last_seen_at > existing_link.last_seen_at:
            session.delete(existing_link)
            session.flush()
            link.job_id = kept_job_id
            moved_source_ids.append(str(link.id))
        else:
            session.delete(link)

    moved_version_ids: list[str] = []
    for version in session.scalars(
        select(JobVersion).where(JobVersion.job_id == merged_job_id)
    ).all():
        existing_version = session.scalar(
            select(JobVersion).where(
                JobVersion.job_id == kept_job_id, JobVersion.content_hash == version.content_hash
            )
        )
        if existing_version is None:
            version.job_id = kept_job_id
            moved_version_ids.append(str(version.id))
        else:
            session.delete(version)

    merged_job.status = "merged"
    merged_job.merged_into_job_id = kept_job_id

    candidate.status = "merged"
    candidate.resolved_at = utcnow()
    candidate.kept_job_id = kept_job_id
    candidate.merged_job_id = merged_job_id
    candidate.moved_job_source_ids = moved_source_ids
    candidate.moved_job_version_ids = moved_version_ids

    session.add(
        SystemEvent(
            user_id=user.id,
            event_type="job_merged",
            entity_type="job",
            entity_id=kept_job_id,
            message=f"Merged job {merged_job_id} into {kept_job_id}",
            data={
                "candidate_id": str(candidate.id),
                "kept_job_id": str(kept_job_id),
                "merged_job_id": str(merged_job_id),
            },
        )
    )
    session.commit()
    session.refresh(candidate)
    return candidate


def unmerge_candidate(session: Session, user: User, candidate_id: uuid.UUID) -> JobMergeCandidate:
    candidate = _get_candidate(session, user, candidate_id)
    if candidate.status != "merged":
        raise MergeCandidateNotMergedError(str(candidate_id))

    merged_job = session.get(Job, candidate.merged_job_id)
    assert merged_job is not None
    kept_job_id = candidate.kept_job_id

    source_ids = [uuid.UUID(value) for value in candidate.moved_job_source_ids]
    if source_ids:
        session.execute(
            update(JobSource).where(JobSource.id.in_(source_ids)).values(job_id=merged_job.id)
        )
    version_ids = [uuid.UUID(value) for value in candidate.moved_job_version_ids]
    if version_ids:
        session.execute(
            update(JobVersion).where(JobVersion.id.in_(version_ids)).values(job_id=merged_job.id)
        )

    merged_job.status = "active"
    merged_job.merged_into_job_id = None

    candidate.status = "dismissed"
    candidate.resolved_at = utcnow()

    session.add(
        SystemEvent(
            user_id=user.id,
            event_type="job_unmerged",
            entity_type="job",
            entity_id=kept_job_id,
            message=f"Unmerged job {merged_job.id} from {kept_job_id}",
            data={"candidate_id": str(candidate.id)},
        )
    )
    session.commit()
    session.refresh(candidate)
    return candidate
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_job_merge_service.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/jose/services/job_merge.py backend/tests/test_job_merge_service.py
git commit -m "feat: add job merge/unmerge service with SystemEvent audit trail"
```

---

## Task 6: API routes for the merge queue

**Files:**
- Modify: `backend/jose/schemas.py`
- Create: `backend/jose/api/routes/job_merge.py`
- Modify: `backend/jose/api/main.py`
- Test: `backend/tests/test_job_merge_api.py` (new file)

**Interfaces:**
- Consumes: `job_merge` service functions and exceptions (Task 5).
- Produces: `GET /api/v1/job-merge-candidates?status=pending`, `POST /api/v1/job-merge-candidates/{id}/resolve`, `POST /api/v1/job-merge-candidates/{id}/unmerge`. Task 7 (web) consumes these three endpoints' JSON shapes exactly as defined here.

Note on scope: the spec mentioned a `JobStatus` schema enum for symmetry with `SourceCategory`/`SourceAdapter`. It is not added here — nothing in this plan reads or validates a `Job.status` value at the API boundary (the existing `JobRead` schema already stores it as a plain `str`, matching today's behavior), so an unused enum would be dead code. If a later issue starts accepting `status` as API input, add it then.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_job_merge_api.py`:

```python
import uuid

from jose.models import Company, Job, JobMergeCandidate


def _make_company(session, user, name="Acme"):
    company = Company(user_id=user.id, name=name, normalized_name=name.lower())
    session.add(company)
    session.flush()
    return company


def _make_job(session, user, company, **overrides):
    defaults = dict(
        user_id=user.id,
        company_id=company.id,
        title="Software Engineer",
        normalized_title="software engineer",
        location="San Francisco, CA",
        application_url="https://acme.example.com/jobs/1",
        canonical_url="https://acme.example.com/jobs/1",
        fingerprint=uuid.uuid4().hex,
        content_hash=uuid.uuid4().hex,
    )
    defaults.update(overrides)
    job = Job(**defaults)
    session.add(job)
    session.flush()
    return job


def _make_candidate(session, user, job, candidate_job):
    candidate = JobMergeCandidate(
        user_id=user.id,
        job_id=job.id,
        candidate_job_id=candidate_job.id,
        similarity_score=0.9,
        matched_signals={"company": 1.0, "title": 1.0, "location": 1.0},
        status="pending",
    )
    session.add(candidate)
    session.flush()
    return candidate


def test_list_job_merge_candidates_returns_job_summaries(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    _make_candidate(db_session, user, job, other)
    db_session.commit()

    response = client.get("/api/v1/job-merge-candidates")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["job"]["company_name"] == "Acme"
    assert body[0]["candidate_job"]["title"] == "Software Engineer"
    assert body[0]["matched_signals"]["company"] == 1.0


def test_resolve_dismiss_marks_candidate_dismissed(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    response = client.post(
        f"/api/v1/job-merge-candidates/{candidate.id}/resolve", json={"action": "dismiss"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


def test_resolve_merge_requires_keep(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    response = client.post(
        f"/api/v1/job-merge-candidates/{candidate.id}/resolve", json={"action": "merge"}
    )

    assert response.status_code == 400


def test_resolve_merge_then_unmerge_round_trip(client, db_session, user):
    company = _make_company(db_session, user)
    job = _make_job(db_session, user, company)
    other = _make_job(db_session, user, company, application_url="https://acme.example.com/2")
    candidate = _make_candidate(db_session, user, job, other)
    db_session.commit()

    merge_response = client.post(
        f"/api/v1/job-merge-candidates/{candidate.id}/resolve",
        json={"action": "merge", "keep": "job"},
    )
    assert merge_response.status_code == 200
    assert merge_response.json()["status"] == "merged"

    unmerge_response = client.post(f"/api/v1/job-merge-candidates/{candidate.id}/unmerge")
    assert unmerge_response.status_code == 200
    assert unmerge_response.json()["status"] == "dismissed"


def test_resolve_unknown_candidate_returns_404(client):
    response = client.post(
        f"/api/v1/job-merge-candidates/{uuid.uuid4()}/resolve", json={"action": "dismiss"}
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_job_merge_api.py -v`
Expected: FAIL — `404 Not Found` for all requests (route does not exist yet)

- [ ] **Step 3: Add the Pydantic schemas**

In `backend/jose/schemas.py`, add (near the other enums, after `CollectionFrequency`):

```python
class JobMergeAction(StrEnum):
    MERGE = "merge"
    DISMISS = "dismiss"


class JobMergeKeep(StrEnum):
    JOB = "job"
    CANDIDATE = "candidate"
```

and, near the end of the file (after `JobRead`), add:

```python
class JobMergeResolveRequest(BaseModel):
    action: JobMergeAction
    keep: JobMergeKeep | None = None


class JobMergeCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    candidate_job_id: uuid.UUID
    status: str
    similarity_score: float
    matched_signals: dict[str, float]
    kept_job_id: uuid.UUID | None
    merged_job_id: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None
```

- [ ] **Step 4: Add the route file**

Create `backend/jose/api/routes/job_merge.py`:

```python
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from jose.api.deps import CurrentUser, DBSession
from jose.models import Company, Job, JobMergeCandidate
from jose.schemas import JobMergeCandidateRead, JobMergeResolveRequest
from jose.services import job_merge as job_merge_service

router = APIRouter(prefix="/api/v1/job-merge-candidates", tags=["job-merge-candidates"])


def _job_summary(db: DBSession, job_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(
        select(Job, Company.name)
        .join(Company, Company.id == Job.company_id)
        .where(Job.id == job_id)
    ).first()
    assert row is not None
    job, company_name = row
    return {
        "id": job.id,
        "title": job.title,
        "company_name": company_name,
        "location": job.location,
        "application_url": job.application_url,
        "status": job.status,
    }


@router.get("")
def list_job_merge_candidates(
    db: DBSession, user: CurrentUser, status: str = Query(default="pending")
) -> list[dict[str, Any]]:
    candidates = job_merge_service.list_merge_candidates(db, user, status)
    return [
        {
            "id": candidate.id,
            "status": candidate.status,
            "similarity_score": candidate.similarity_score,
            "matched_signals": candidate.matched_signals,
            "created_at": candidate.created_at,
            "job": _job_summary(db, candidate.job_id),
            "candidate_job": _job_summary(db, candidate.candidate_job_id),
        }
        for candidate in candidates
    ]


@router.post("/{candidate_id}/resolve", response_model=JobMergeCandidateRead)
def resolve_job_merge_candidate(
    candidate_id: uuid.UUID, payload: JobMergeResolveRequest, db: DBSession, user: CurrentUser
) -> JobMergeCandidate:
    try:
        if payload.action == "dismiss":
            return job_merge_service.dismiss_merge_candidate(db, user, candidate_id)
        if payload.keep is None:
            raise HTTPException(status_code=400, detail="keep is required for merge action")
        return job_merge_service.merge_candidate(db, user, candidate_id, payload.keep)
    except job_merge_service.MergeCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Merge candidate not found") from exc
    except job_merge_service.MergeCandidateNotPendingError as exc:
        raise HTTPException(status_code=409, detail="Merge candidate already resolved") from exc


@router.post("/{candidate_id}/unmerge", response_model=JobMergeCandidateRead)
def unmerge_job_merge_candidate(
    candidate_id: uuid.UUID, db: DBSession, user: CurrentUser
) -> JobMergeCandidate:
    try:
        return job_merge_service.unmerge_candidate(db, user, candidate_id)
    except job_merge_service.MergeCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Merge candidate not found") from exc
    except job_merge_service.MergeCandidateNotMergedError as exc:
        raise HTTPException(status_code=409, detail="Merge candidate is not merged") from exc
```

- [ ] **Step 5: Register the router**

In `backend/jose/api/main.py`, change:

```python
from jose.api.routes import admin, dashboard, health, imports, jobs, sources, tasks
```

to:

```python
from jose.api.routes import admin, dashboard, health, imports, job_merge, jobs, sources, tasks
```

and add, alongside the other `app.include_router(...)` calls:

```python
app.include_router(job_merge.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_job_merge_api.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Run the full backend suite and ruff**

Run: `docker compose run --rm api sh -c "ruff check jose tests && pytest -v"`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/jose/schemas.py backend/jose/api/routes/job_merge.py backend/jose/api/main.py backend/tests/test_job_merge_api.py
git commit -m "feat: add job merge candidate API endpoints"
```

---

## Task 7: Web — review queue page

**Files:**
- Modify: `web/lib/api.ts`
- Create: `web/components/job-merge-review.tsx`
- Create: `web/app/jobs/review/page.tsx`
- Modify: `web/components/nav.tsx`
- Modify: `web/app/jobs/page.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/job-merge-candidates`, `POST /api/v1/job-merge-candidates/{id}/resolve` (Task 6).
- Produces: the `/jobs/review` page. No later task depends on this one.

This task has no automated test framework to extend (the web app has none today — `BUILD_STATUS.md` documents verification via `tsc --noEmit`, `eslint`, and `next build` for every prior frontend change; there is no unit-test runner configured). Its "test cycle" is those three commands plus a manual pass against the running app.

- [ ] **Step 1: Add types and a fetcher to `web/lib/api.ts`**

Add near the other `type` declarations (after `Job`):

```typescript
export type JobMergeSummary = {
  id: string;
  title: string;
  company_name: string;
  location: string | null;
  application_url: string;
  status: string;
};

export type JobMergeCandidate = {
  id: string;
  status: string;
  similarity_score: number;
  matched_signals: { company: number; title: number; location: number };
  created_at: string;
  job: JobMergeSummary;
  candidate_job: JobMergeSummary;
};
```

Add near the other `get*` functions (after `getJobs`):

```typescript
export async function getJobMergeCandidates(): Promise<JobMergeCandidate[]> {
  return getJson<JobMergeCandidate[]>("/api/v1/job-merge-candidates?status=pending");
}
```

- [ ] **Step 2: Create `web/components/job-merge-review.tsx`**

```tsx
"use client";

import { useState } from "react";
import type { JobMergeCandidate } from "@/lib/api";
import { apiFetchJson } from "@/lib/browser-api";

function formatScore(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function JobMergeReview({
  initialCandidates,
}: {
  initialCandidates: JobMergeCandidate[];
}) {
  const [candidates, setCandidates] = useState(initialCandidates);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function resolve(candidateId: string, body: Record<string, unknown>) {
    setError(null);
    setBusyId(candidateId);
    try {
      await apiFetchJson(`/api/v1/job-merge-candidates/${candidateId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setCandidates((current) => current.filter((c) => c.id !== candidateId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  if (!candidates.length) {
    return <p className="emptyState">No potential duplicates waiting for review.</p>;
  }

  return (
    <>
      {error ? <p className="formError">{error}</p> : null}
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Possible duplicate</th>
              <th>Match</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.id}>
                <td>
                  <strong>{candidate.job.title}</strong>
                  <small>
                    {candidate.job.company_name} —{" "}
                    {candidate.job.location ?? "Location not listed"}
                  </small>
                </td>
                <td>
                  <strong>{candidate.candidate_job.title}</strong>
                  <small>
                    {candidate.candidate_job.company_name} —{" "}
                    {candidate.candidate_job.location ?? "Location not listed"}
                  </small>
                </td>
                <td>
                  <span>{formatScore(candidate.similarity_score)} overall</span>
                  <small>
                    company {formatScore(candidate.matched_signals.company)}, title{" "}
                    {formatScore(candidate.matched_signals.title)}, location{" "}
                    {formatScore(candidate.matched_signals.location)}
                  </small>
                </td>
                <td>
                  <div className="rowActions">
                    <button
                      type="button"
                      disabled={busyId === candidate.id}
                      onClick={() => resolve(candidate.id, { action: "merge", keep: "job" })}
                    >
                      Keep first, merge
                    </button>
                    <button
                      type="button"
                      disabled={busyId === candidate.id}
                      onClick={() =>
                        resolve(candidate.id, { action: "merge", keep: "candidate" })
                      }
                    >
                      Keep second, merge
                    </button>
                    <button
                      type="button"
                      className="ghostButton"
                      disabled={busyId === candidate.id}
                      onClick={() => resolve(candidate.id, { action: "dismiss" })}
                    >
                      Not a duplicate
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
```

- [ ] **Step 3: Create `web/app/jobs/review/page.tsx`**

```tsx
import { JobMergeReview } from "@/components/job-merge-review";
import { getJobMergeCandidates } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function JobMergeReviewPage() {
  const candidates = await getJobMergeCandidates();
  return (
    <section>
      <div className="pageHeader">
        <div>
          <p className="eyebrow">Deduplication</p>
          <h1>Review queue</h1>
          <p>Possible duplicate jobs JOSE isn&apos;t confident enough to merge automatically.</p>
        </div>
        <span className="countPill">{candidates.length} pending</span>
      </div>
      <JobMergeReview initialCandidates={candidates} />
    </section>
  );
}
```

- [ ] **Step 4: Link the page from navigation and the Jobs page**

In `web/components/nav.tsx`, change:

```tsx
const links = [
  ["Dashboard", "/"],
  ["Sources", "/sources"],
  ["Jobs", "/jobs"],
] as const;
```

to:

```tsx
const links = [
  ["Dashboard", "/"],
  ["Sources", "/sources"],
  ["Jobs", "/jobs"],
  ["Review queue", "/jobs/review"],
] as const;
```

In `web/app/jobs/page.tsx`, add the `Link` import and wrap the existing count pill in a `rowActions` div with a link to the review page, matching the pattern already used on `web/app/sources/page.tsx`. Change:

```tsx
import { getJobs } from "@/lib/api";

export const dynamic = "force-dynamic";
```

to:

```tsx
import Link from "next/link";
import { getJobs } from "@/lib/api";

export const dynamic = "force-dynamic";
```

and change:

```tsx
        <span className="countPill">{jobs.length} shown</span>
      </div>
```

to:

```tsx
        <div className="rowActions">
          <Link className="primaryAction ghostButton" href="/jobs/review">
            Review possible duplicates
          </Link>
          <span className="countPill">{jobs.length} shown</span>
        </div>
      </div>
```

- [ ] **Step 5: Type-check, lint, and build**

Run: `docker compose run --rm web npx tsc --noEmit`
Expected: no errors

Run: `docker compose run --rm web npm run lint`
Expected: no errors

Run: `docker compose run --rm -v /app/.next web npm run build`
Expected: build succeeds

- [ ] **Step 6: Manual smoke test**

With `make dev` running, use a merge candidate created by the Task 4 tests' scenario (or trigger one by adding two sources whose collected jobs are near-duplicates, then running `make collect-all`), then open `http://localhost:3000/jobs/review` in a browser and confirm: pending pairs render with both jobs' details and match percentages, "Not a duplicate" removes the row and the candidate's `status` becomes `dismissed` (verify via `GET /api/v1/job-merge-candidates?status=dismissed`), and a merge action removes the row and the merged-away job's `status` becomes `merged` (verify via the jobs API or database).

- [ ] **Step 7: Commit**

```bash
git add web/lib/api.ts web/components/job-merge-review.tsx web/app/jobs/review/page.tsx web/components/nav.tsx web/app/jobs/page.tsx
git commit -m "feat: add job merge review queue page"
```

---

## Task 8: Full verification pass

**Files:** none (verification only)

**Interfaces:** none — this task confirms Tasks 1–7 integrate correctly as a whole.

- [ ] **Step 1: Fresh migration check**

Run: `docker compose down -v && docker compose up -d db && docker compose run --rm api alembic upgrade head`
Expected: all five migrations (`0001` through `0005_job_merge_candidates`) apply cleanly against an empty database.

- [ ] **Step 2: Full backend suite and lint**

Run: `docker compose run --rm api sh -c "ruff check jose tests && pytest -v"`
Expected: PASS, no ruff findings.

- [ ] **Step 3: Full frontend checks**

Run: `docker compose run --rm web npx tsc --noEmit && docker compose run --rm web npm run lint && docker compose run --rm -v /app/.next web npm run build`
Expected: PASS.

- [ ] **Step 4: End-to-end smoke test**

Run: `make dev`, then in another terminal `make seed && make import-sources && make collect-all`. Confirm the API and web app both start cleanly, `/jobs` and `/jobs/review` render without errors, and `GET /api/v1/job-merge-candidates` returns `200` (empty list is fine — the existing OpenAI/Anthropic sources don't overlap, so no real candidates are expected from this run; this step is checking nothing is broken, not that dedup fires).

- [ ] **Step 5: Commit (if anything changed during verification)**

If Step 1–4 required no code changes, there is nothing to commit — Tasks 1–7 already committed everything. If any threshold tuning or fix was needed, commit it now with a message describing what verification caught.
