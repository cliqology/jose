# Harden the Database-Backed Task Queue (Issue 09) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make background work cloud-safe without adding Redis, per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 09 and `docs/superpowers/specs/2026-07-30-harden-task-queue-design.md`.

**Architecture:** `backend/jose/services/tasks.py` already implements a correct `SKIP LOCKED` claim query; this plan adds exponential backoff with jitter on retry (reusing the existing `scheduled_at` column), a single-statement `UPDATE ... RETURNING` reaper for stale `"running"` tasks, a per-process worker identity with graceful `SIGTERM`/`SIGINT` handling, a `payload_version` column, a per-user `timezone` column that fixes daily-collection idempotency, and a `SystemEvent` audit row on terminal task failure. No new infrastructure or process.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, pytest. All backend commands run via `docker compose run --rm api ...` (Colima-backed Docker per `[[docker_environment_colima]]`).

## Global Constraints

- Every task must be idempotent and safely retryable (CLAUDE.md rule #9) — this issue exists to make that true in practice, not just in principle.
- Long-running work belongs in a worker task, not an HTTP request (CLAUDE.md rule #8) — unaffected by this issue; no route does work inline.
- Every user-owned record includes `user_id`; use timezone-aware UTC datetimes; use UUID primary keys (CLAUDE.md architecture rules).
- Add a migration whenever the persisted schema changes (CLAUDE.md working rule).
- Use fixtures for tests. No live network calls in unit tests.
- Ruff must pass (line length 100, rules E/F/I/B/UP/SIM per `backend/pyproject.toml`).
- Definition of done: acceptance criteria met, unit tests pass, ruff passes, migration included, error paths handled, no unsupported claim or hidden automation introduced.
- Prefer boring, inexpensive infrastructure (CLAUDE.md) — a fixed timeout since `started_at` for stale detection, not a heartbeat mechanism; the reaper runs inline in the existing poll loop, not as a separate process or cron job (approved design decisions).

---

## Task 1: Data model — `Task.payload_version` and `User.timezone`

**Files:**
- Modify: `backend/jose/models/core.py:23-28` (`User` class), `:207-225` (`Task` class)
- Create: `backend/alembic/versions/0007_harden_task_queue.py`
- Test: `backend/tests/test_tasks.py` (new file)

**Interfaces:**
- Consumes: nothing from earlier tasks (first task).
- Produces: `User.timezone: str` and `Task.payload_version: int`. Task 5 relies on `User.timezone`. `Task.payload_version` has no consumer yet in this plan (it exists for future payload-shape evolution, per the design doc) but must exist and default correctly.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_tasks.py`:

```python
from jose.models import Task, User


def test_user_timezone_defaults_to_america_los_angeles(db_session, user):
    assert user.timezone == "America/Los_Angeles"


def test_task_payload_version_defaults_to_one(db_session, user):
    task = Task(
        user_id=user.id,
        task_type="collect_source",
        payload={"source_id": "abc"},
        idempotency_key="payload-version-default",
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    assert task.payload_version == 1
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v`
Expected: FAIL — `AttributeError` on `user.timezone` and `task.payload_version` (neither column exists on the ORM models yet).

- [ ] **Step 3: Add `timezone` to `User`**

In `backend/jose/models/core.py`, change:

```python
class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

to:

```python
class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(50), default="America/Los_Angeles", nullable=False
    )
```

- [ ] **Step 4: Add `payload_version` to `Task`**

In the same file, change:

```python
    task_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
```

to:

```python
    task_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/0007_harden_task_queue.py`:

```python
"""Add task payload versioning and user timezone.

Revision ID: 0007_harden_task_queue
Revises: 0006_job_removal_detection
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_harden_task_queue"
down_revision = "0006_job_removal_detection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("payload_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(length=50),
            nullable=False,
            server_default="America/Los_Angeles",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
    op.drop_column("tasks", "payload_version")
```

- [ ] **Step 6: Apply the migration and run the tests**

Run: `docker compose run --rm api sh -c "alembic upgrade head && pytest tests/test_tasks.py -v"`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/jose/models/core.py backend/alembic/versions/0007_harden_task_queue.py backend/tests/test_tasks.py
git commit -m "feat: add task payload versioning and user timezone columns"
```

---

## Task 2: Retry backoff with jitter and terminal-failure audit event

**Files:**
- Modify: `backend/jose/config.py` (add retry `Settings` fields)
- Modify: `backend/jose/services/tasks.py` (imports; new `backoff_delay`; `run_task`'s failure branch)
- Test: `backend/tests/test_tasks.py`

**Interfaces:**
- Consumes: nothing from earlier tasks besides the schema from Task 1 (not directly used here, but `Task` rows now carry `payload_version`, unaffected by this task).
- Produces: `jose.services.tasks.backoff_delay(attempts: int) -> timedelta`. `run_task` now requeues a retryable failure with a future `scheduled_at` instead of an immediate one, and emits a `SystemEvent(event_type="task_failed")` when a task reaches `status == "failed"`. Task 3's reaper reuses this same "queued vs. failed by attempts" branching logic independently (no shared helper needed — see Task 3).

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `backend/tests/test_tasks.py` with:

```python
from datetime import UTC, datetime

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task, User
from jose.services.tasks import backoff_delay, claim_next_task, enqueue_task, run_task


def test_user_timezone_defaults_to_america_los_angeles(db_session, user):
    assert user.timezone == "America/Los_Angeles"


def test_task_payload_version_defaults_to_one(db_session, user):
    task = Task(
        user_id=user.id,
        task_type="collect_source",
        payload={"source_id": "abc"},
        idempotency_key="payload-version-default",
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    assert task.payload_version == 1


def test_backoff_delay_doubles_and_stays_within_jitter_bounds():
    settings = get_settings()
    for attempts, expected_base in [(1, 60.0), (2, 120.0), (3, 240.0)]:
        delay = backoff_delay(attempts)
        jitter = expected_base * settings.task_retry_jitter_pct
        assert expected_base - jitter <= delay.total_seconds() <= expected_base + jitter


def test_backoff_delay_caps_at_max_seconds():
    settings = get_settings()
    delay = backoff_delay(10)
    jitter = settings.task_retry_max_seconds * settings.task_retry_jitter_pct
    assert delay.total_seconds() <= settings.task_retry_max_seconds + jitter


def test_failed_task_requeues_with_future_scheduled_at_before_final_attempt(db_session, user):
    task = enqueue_task(
        db_session,
        user,
        task_type="unsupported_test_type",
        payload={},
        idempotency_key="retry-test-1",
    )
    task.max_attempts = 2
    db_session.commit()

    claimed = claim_next_task(db_session, "test-worker")
    assert claimed.id == task.id

    run_task(db_session, claimed)

    db_session.refresh(task)
    assert task.status == "queued"
    assert task.attempts == 1
    assert task.scheduled_at > datetime.now(UTC)
    assert claim_next_task(db_session, "test-worker") is None


def test_task_failed_terminally_emits_system_event(db_session, user):
    task = enqueue_task(
        db_session,
        user,
        task_type="unsupported_test_type",
        payload={},
        idempotency_key="retry-test-2",
    )
    task.max_attempts = 1
    db_session.commit()

    claimed = claim_next_task(db_session, "test-worker")
    run_task(db_session, claimed)

    db_session.refresh(task)
    assert task.status == "failed"

    event = db_session.scalar(
        select(SystemEvent).where(
            SystemEvent.entity_id == task.id, SystemEvent.event_type == "task_failed"
        )
    )
    assert event is not None
    assert event.data["attempts"] == 1
```

(`User` stays imported for the Task 1 tests even though this file no longer references it directly by name in new tests — it's still used by the `user` fixture's type, not by these tests' bodies, so drop it only if ruff's `F401` flags it. It will not: `User` is not referenced anywhere else in this file, so remove it from the import to keep ruff clean — see the corrected import list below.)

Use this import block instead (drops the unused `User` symbol):

```python
from datetime import UTC, datetime

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.services.tasks import backoff_delay, claim_next_task, enqueue_task, run_task
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v`
Expected: FAIL — `ImportError: cannot import name 'backoff_delay' from 'jose.services.tasks'` (the two Task 1 tests still pass once this import error is fixed at the top of the collection process; until then the whole file fails to collect).

- [ ] **Step 3: Add retry `Settings` fields**

In `backend/jose/config.py`, change:

```python
    worker_poll_seconds: float = 2.0
    worker_id: str = "jose-worker"
```

to:

```python
    worker_poll_seconds: float = 2.0
    worker_id: str = "jose-worker"
    task_retry_base_seconds: float = 60.0
    task_retry_max_seconds: float = 1800.0
    task_retry_jitter_pct: float = 0.2
```

- [ ] **Step 4: Update imports in `services/tasks.py`**

In `backend/jose/services/tasks.py`, change:

```python
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jose.config import get_settings
from jose.db.session import SessionLocal
from jose.models import Source, Task, User
from jose.services.collection import collect_source
```

to:

```python
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jose.config import get_settings
from jose.db.session import SessionLocal
from jose.models import Source, SystemEvent, Task, User
from jose.services.collection import collect_source
```

- [ ] **Step 5: Add `backoff_delay`**

In `backend/jose/services/tasks.py`, add this function directly after `claim_next_task` (before `run_task`):

```python
def backoff_delay(attempts: int) -> timedelta:
    settings = get_settings()
    base = min(
        settings.task_retry_base_seconds * (2 ** (attempts - 1)),
        settings.task_retry_max_seconds,
    )
    jitter = base * settings.task_retry_jitter_pct
    seconds = random.uniform(base - jitter, base + jitter)
    return timedelta(seconds=seconds)
```

- [ ] **Step 6: Requeue with backoff and audit terminal failure**

In `backend/jose/services/tasks.py`, change `run_task`'s failure branch:

```python
    except Exception as exc:
        session.rollback()
        task = session.get(Task, task.id)
        if task:
            task.last_error = f"{type(exc).__name__}: {exc}"
            task.completed_at = utcnow()
            task.status = "queued" if task.attempts < task.max_attempts else "failed"
            session.commit()
```

to:

```python
    except Exception as exc:
        session.rollback()
        task = session.get(Task, task.id)
        if task:
            task.last_error = f"{type(exc).__name__}: {exc}"
            task.completed_at = utcnow()
            if task.attempts < task.max_attempts:
                task.status = "queued"
                task.scheduled_at = utcnow() + backoff_delay(task.attempts)
            else:
                task.status = "failed"
                session.add(
                    SystemEvent(
                        user_id=task.user_id,
                        event_type="task_failed",
                        entity_type="task",
                        entity_id=task.id,
                        message=(
                            f"Task {task.id} ({task.task_type}) failed permanently "
                            f"after {task.attempts} attempts"
                        ),
                        data={
                            "task_type": task.task_type,
                            "attempts": task.attempts,
                            "last_error": task.last_error,
                        },
                    )
                )
            session.commit()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/jose/config.py backend/jose/services/tasks.py backend/tests/test_tasks.py
git commit -m "feat: add retry backoff with jitter and audit terminal task failures"
```

---

## Task 3: Stale running-task reaper

**Files:**
- Modify: `backend/jose/config.py` (add `task_stale_running_minutes`)
- Modify: `backend/jose/services/tasks.py` (imports; new `reap_stale_tasks`; wire into `worker_loop`)
- Test: `backend/tests/test_tasks.py`

**Interfaces:**
- Consumes: `SystemEvent` (Task 2's import), the existing `Task.attempts`/`max_attempts` fields.
- Produces: `jose.services.tasks.reap_stale_tasks(session: Session, threshold: timedelta) -> list[Task]`. `worker_loop` now calls this once per iteration before `claim_next_task`. Task 4 edits `worker_loop` again on top of this task's version.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_tasks.py`, change the import block:

```python
from datetime import UTC, datetime

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.services.tasks import backoff_delay, claim_next_task, enqueue_task, run_task
```

to:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.services.tasks import (
    backoff_delay,
    claim_next_task,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)
```

Append to the end of the file:

```python
def test_reap_stale_tasks_requeues_when_attempts_remain(db_session, user):
    task = enqueue_task(
        db_session, user, task_type="collect_source", payload={}, idempotency_key="stale-1"
    )
    claim_next_task(db_session, "worker-a")
    db_session.refresh(task)
    task.started_at = datetime.now(UTC) - timedelta(minutes=45)
    db_session.commit()

    reaped = reap_stale_tasks(db_session, timedelta(minutes=30))

    assert len(reaped) == 1
    db_session.refresh(task)
    assert task.status == "queued"

    event = db_session.scalar(
        select(SystemEvent).where(
            SystemEvent.entity_id == task.id, SystemEvent.event_type == "task_reaped_stale"
        )
    )
    assert event is not None
    assert event.data["worker_id"] == "worker-a"


def test_reap_stale_tasks_fails_when_attempts_exhausted(db_session, user):
    task = enqueue_task(
        db_session, user, task_type="collect_source", payload={}, idempotency_key="stale-2"
    )
    task.max_attempts = 1
    db_session.commit()
    claim_next_task(db_session, "worker-a")
    db_session.refresh(task)
    task.started_at = datetime.now(UTC) - timedelta(minutes=45)
    db_session.commit()

    reap_stale_tasks(db_session, timedelta(minutes=30))

    db_session.refresh(task)
    assert task.status == "failed"


def test_reap_stale_tasks_leaves_recent_running_tasks_alone(db_session, user):
    task = enqueue_task(
        db_session, user, task_type="collect_source", payload={}, idempotency_key="stale-3"
    )
    claim_next_task(db_session, "worker-a")

    reaped = reap_stale_tasks(db_session, timedelta(minutes=30))

    assert reaped == []
    db_session.refresh(task)
    assert task.status == "running"


def test_worker_loop_once_reaps_stale_task_before_claiming(db_session, user):
    task = enqueue_task(
        db_session,
        user,
        task_type="unsupported_test_type",
        payload={},
        idempotency_key="stale-loop-1",
    )
    task.max_attempts = 5
    db_session.commit()
    claim_next_task(db_session, "dead-worker")
    db_session.refresh(task)
    task.started_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()

    worker_loop(once=True)

    db_session.expire_all()
    db_session.refresh(task)
    assert task.attempts == 2
    assert task.status == "queued"
    assert task.scheduled_at > datetime.now(UTC)
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v -k "stale"`
Expected: FAIL — `ImportError: cannot import name 'reap_stale_tasks' from 'jose.services.tasks'`.

- [ ] **Step 3: Add `task_stale_running_minutes` to `Settings`**

In `backend/jose/config.py`, change:

```python
    task_retry_base_seconds: float = 60.0
    task_retry_max_seconds: float = 1800.0
    task_retry_jitter_pct: float = 0.2
```

to:

```python
    task_retry_base_seconds: float = 60.0
    task_retry_max_seconds: float = 1800.0
    task_retry_jitter_pct: float = 0.2
    task_stale_running_minutes: float = 30.0
```

- [ ] **Step 4: Update imports in `services/tasks.py`**

Change:

```python
from sqlalchemy import select
```

to:

```python
from sqlalchemy import case, select, update
```

- [ ] **Step 5: Add `reap_stale_tasks`**

Add this function directly after `run_task` (before `worker_loop`):

```python
def reap_stale_tasks(session: Session, threshold: timedelta) -> list[Task]:
    cutoff = utcnow() - threshold
    stmt = (
        update(Task)
        .where(Task.status == "running", Task.started_at < cutoff)
        .values(
            status=case((Task.attempts < Task.max_attempts, "queued"), else_="failed"),
            scheduled_at=utcnow(),
        )
        .returning(Task)
    )
    reaped = list(session.execute(stmt).scalars().all())
    for task in reaped:
        session.add(
            SystemEvent(
                user_id=task.user_id,
                event_type="task_reaped_stale",
                entity_type="task",
                entity_id=task.id,
                message=(
                    f"Reaped stale running task {task.id} ({task.task_type}), "
                    f"last held by worker {task.worker_id}"
                ),
                data={
                    "worker_id": task.worker_id,
                    "attempts": task.attempts,
                    "status": task.status,
                },
            )
        )
    session.commit()
    return reaped
```

- [ ] **Step 6: Wire the reaper into `worker_loop`**

Change:

```python
def worker_loop(once: bool = False) -> None:
    settings = get_settings()
    while True:
        with SessionLocal() as session:
            task = claim_next_task(session, settings.worker_id)
            if task:
                run_task(session, task)
            elif once:
                return
        if once:
            return
        time.sleep(settings.worker_poll_seconds)
```

to:

```python
def worker_loop(once: bool = False) -> None:
    settings = get_settings()
    while True:
        with SessionLocal() as session:
            reap_stale_tasks(session, timedelta(minutes=settings.task_stale_running_minutes))
            task = claim_next_task(session, settings.worker_id)
            if task:
                run_task(session, task)
            elif once:
                return
        if once:
            return
        time.sleep(settings.worker_poll_seconds)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v`
Expected: PASS (10 tests)

- [ ] **Step 8: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/jose/config.py backend/jose/services/tasks.py backend/tests/test_tasks.py
git commit -m "feat: recover stale running tasks with a per-cycle reaper"
```

---

## Task 4: Per-process worker identity and graceful shutdown

**Files:**
- Modify: `backend/jose/config.py` (remove `worker_id`)
- Modify: `backend/jose/services/tasks.py` (imports; new `_worker_identity`; rewrite `worker_loop`)
- Test: `backend/tests/test_tasks.py`

**Interfaces:**
- Consumes: `reap_stale_tasks` (Task 3).
- Produces: `jose.services.tasks._worker_identity() -> str` (module-private). `worker_loop` gains an optional `stop_event: threading.Event | None = None` parameter — production callers (`cli.py`) omit it and get real `SIGTERM`/`SIGINT` handling; tests pass their own `Event` to drive shutdown deterministically without sending OS signals. This is the last task that touches `worker_loop`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_tasks.py`, change the import block:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.services.tasks import (
    backoff_delay,
    claim_next_task,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)
```

to:

```python
import os
import socket
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.services.tasks import (
    _worker_identity,
    backoff_delay,
    claim_next_task,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)
from jose.services import tasks as tasks_module
```

(Two import lines from the same top-level package — `jose.services.tasks` symbols and the `jose.services.tasks` module itself under an alias — are both needed: the first for direct calls, the second (`tasks_module`) so the shutdown test can `monkeypatch.setattr` a function on the module.)

Append to the end of the file:

```python
def test_worker_identity_includes_hostname_and_pid():
    identity_a = tasks_module._worker_identity()
    identity_b = tasks_module._worker_identity()

    assert identity_a.startswith(f"{socket.gethostname()}-{os.getpid()}-")
    assert identity_a != identity_b


def test_worker_loop_finishes_current_task_then_stops_on_shutdown(db_session, user, monkeypatch):
    task = enqueue_task(
        db_session,
        user,
        task_type="collect_source",
        payload={},
        idempotency_key="shutdown-1",
    )
    stop_event = threading.Event()
    original_claim = tasks_module.claim_next_task
    calls = []

    def _claim_then_request_shutdown(session, worker_id):
        calls.append(1)
        claimed = original_claim(session, worker_id)
        stop_event.set()
        return claimed

    monkeypatch.setattr(tasks_module, "claim_next_task", _claim_then_request_shutdown)

    tasks_module.worker_loop(once=False, stop_event=stop_event)

    assert calls == [1]
    db_session.expire_all()
    db_session.refresh(task)
    assert task.attempts == 1
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v -k "identity or shutdown"`
Expected: FAIL — `ImportError: cannot import name '_worker_identity'`; once that's fixed, the shutdown test fails with `TypeError: worker_loop() got an unexpected keyword argument 'stop_event'`.

- [ ] **Step 3: Remove `worker_id` from `Settings`**

In `backend/jose/config.py`, change:

```python
    worker_poll_seconds: float = 2.0
    worker_id: str = "jose-worker"
    task_retry_base_seconds: float = 60.0
```

to:

```python
    worker_poll_seconds: float = 2.0
    task_retry_base_seconds: float = 60.0
```

- [ ] **Step 4: Update imports in `services/tasks.py`**

Change:

```python
import random
import time
import uuid
from datetime import UTC, datetime, timedelta
```

to:

```python
import os
import random
import signal
import socket
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
```

- [ ] **Step 5: Add `_worker_identity` and rewrite `worker_loop`**

Change:

```python
def worker_loop(once: bool = False) -> None:
    settings = get_settings()
    while True:
        with SessionLocal() as session:
            reap_stale_tasks(session, timedelta(minutes=settings.task_stale_running_minutes))
            task = claim_next_task(session, settings.worker_id)
            if task:
                run_task(session, task)
            elif once:
                return
        if once:
            return
        time.sleep(settings.worker_poll_seconds)
```

to:

```python
def _worker_identity() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def worker_loop(once: bool = False, stop_event: threading.Event | None = None) -> None:
    settings = get_settings()
    worker_id = _worker_identity()
    owns_event = stop_event is None
    stop_event = stop_event or threading.Event()
    previous_handlers: dict[int, object] = {}

    if owns_event:

        def _handle_signal(signum, frame):
            stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(sig, _handle_signal)

    try:
        while True:
            if stop_event.is_set():
                return
            with SessionLocal() as session:
                reap_stale_tasks(
                    session, timedelta(minutes=settings.task_stale_running_minutes)
                )
                task = claim_next_task(session, worker_id)
                if task:
                    run_task(session, task)
                elif once:
                    return
            if once:
                return
            time.sleep(settings.worker_poll_seconds)
    finally:
        if owns_event:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
```

`stop_event` is only checked between iterations — a task claimed by `claim_next_task` always runs to completion via `run_task` before the next check, so shutdown never interrupts in-flight work. When `worker_loop` installs its own signal handlers (`stop_event=None`, the production path used by `cli.py`'s `worker` command), it restores whatever handlers were previously registered on exit, so a test — or a second call in the same process — never leaks a dangling handler.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v`
Expected: PASS (12 tests)

- [ ] **Step 7: Run the full backend suite and ruff**

Run: `docker compose run --rm api sh -c "pytest -v && ruff check ."`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/jose/config.py backend/jose/services/tasks.py backend/tests/test_tasks.py
git commit -m "feat: give each worker a unique identity and shut down gracefully"
```

---

## Task 5: Timezone-aware daily collection idempotency

**Files:**
- Modify: `backend/jose/services/tasks.py` (imports; `enqueue_collect_all`)
- Test: `backend/tests/test_tasks.py`

**Interfaces:**
- Consumes: `User.timezone` (Task 1).
- Produces: no new public interface — `enqueue_collect_all`'s idempotency key now reflects the user's local day instead of the UTC day. Last task that touches production code in this plan.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_tasks.py`, change the import block:

```python
import os
import socket
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.services.tasks import (
    _worker_identity,
    backoff_delay,
    claim_next_task,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)
from jose.services import tasks as tasks_module
```

to:

```python
import os
import socket
import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.schemas import SourceCreate
from jose.services.sources import create_source
from jose.services.tasks import (
    _worker_identity,
    backoff_delay,
    claim_next_task,
    enqueue_collect_all,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)
from jose.services import tasks as tasks_module
```

Append to the end of the file:

```python
def test_enqueue_collect_all_uses_users_timezone_for_idempotency_key(db_session, user):
    user.timezone = "Pacific/Kiritimati"
    db_session.commit()

    source = create_source(
        db_session, user, SourceCreate(name="Acme", url="https://acme-tz.example.com/jobs")
    )

    first_batch = enqueue_collect_all(db_session, user)
    assert len(first_batch) == 1

    second_batch = enqueue_collect_all(db_session, user)
    assert len(second_batch) == 0

    expected_key = (
        f"collect_source:{source.id}:"
        f"{datetime.now(ZoneInfo('Pacific/Kiritimati')).date().isoformat()}"
    )
    assert first_batch[0].idempotency_key == expected_key
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v -k timezone`
Expected: FAIL — `expected_key` (computed in `Pacific/Kiritimati`, UTC+14) does not match the actual idempotency key (still computed from `utcnow().date()`), so the assertion on `first_batch[0].idempotency_key` fails.

- [ ] **Step 3: Update imports in `services/tasks.py`**

Change:

```python
from datetime import UTC, datetime, timedelta
```

to:

```python
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
```

- [ ] **Step 4: Compute `date_key` in the user's timezone**

In `backend/jose/services/tasks.py`, change:

```python
    date_key = utcnow().date().isoformat()
```

to:

```python
    date_key = datetime.now(ZoneInfo(user.timezone)).date().isoformat()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v`
Expected: PASS (13 tests)

- [ ] **Step 6: Run the full backend suite to check for regressions**

Run: `docker compose run --rm api pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/jose/services/tasks.py backend/tests/test_tasks.py
git commit -m "fix: compute daily collection idempotency in the user's timezone"
```

---

## Task 6: Pin concurrent-claim safety under real thread contention

**Files:**
- Test only: `backend/tests/test_tasks.py`

**Interfaces:**
- Consumes: `claim_next_task`, `enqueue_task` (existing), `SessionLocal` (existing).
- Produces: nothing — this task adds test coverage only. `claim_next_task`'s `SELECT ... FOR UPDATE SKIP LOCKED` is already correct and untouched; no production code changes in this task.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_tasks.py`, change the import block:

```python
import os
import socket
import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
from jose.schemas import SourceCreate
from jose.services.sources import create_source
from jose.services.tasks import (
    _worker_identity,
    backoff_delay,
    claim_next_task,
    enqueue_collect_all,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)
from jose.services import tasks as tasks_module
```

to:

```python
import os
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jose.config import get_settings
from jose.db.session import SessionLocal
from jose.models import SystemEvent, Task
from jose.schemas import SourceCreate
from jose.services.sources import create_source
from jose.services.tasks import (
    _worker_identity,
    backoff_delay,
    claim_next_task,
    enqueue_collect_all,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)
from jose.services import tasks as tasks_module
```

Append to the end of the file:

```python
def test_concurrent_claims_never_return_the_same_task(db_session, user):
    for i in range(20):
        enqueue_task(
            db_session,
            user,
            task_type="collect_source",
            payload={},
            idempotency_key=f"concurrent-{i}",
        )

    claimed_ids: list[uuid.UUID] = []
    lock = threading.Lock()

    def _claim_all(worker_id: str) -> None:
        with SessionLocal() as session:
            while True:
                task = claim_next_task(session, worker_id)
                if task is None:
                    return
                with lock:
                    claimed_ids.append(task.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_claim_all, f"worker-{i}") for i in range(2)]
        for future in futures:
            future.result()

    assert len(claimed_ids) == 20
    assert len(set(claimed_ids)) == 20
```

- [ ] **Step 2: Run the test to verify it passes immediately**

Run: `docker compose run --rm api pytest tests/test_tasks.py -v -k concurrent`
Expected: PASS — this test exercises existing, already-correct behavior (`claim_next_task`'s `SKIP LOCKED` query, unchanged by this plan); it pins that behavior rather than driving new production code. If it fails, that's a genuine regression to investigate, not an expected red step.

- [ ] **Step 3: Run the full backend suite and ruff**

Run: `docker compose run --rm api sh -c "pytest -v && ruff check ."`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_tasks.py
git commit -m "test: pin concurrent task claims never double-assign under thread contention"
```

---

## Out of scope (per approved design)

- Any dashboard/UI surfacing of failed or reaped tasks — Issue 10's Source Health dashboard.
- A heartbeat mechanism for stale detection — a fixed timeout since `started_at` is used instead.
- Per-user configurable retry/backoff/stale-timeout values — these stay operator-level `Settings`, not user-facing preferences.
- Priority-queue changes, task cancellation, or a task history/audit UI beyond the `SystemEvent` rows this plan adds.
