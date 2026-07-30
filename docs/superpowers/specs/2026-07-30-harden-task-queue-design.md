# Design: Harden the Database-Backed Task Queue (Issue 09)

## Goal

Make background work cloud-safe without adding Redis, per
`docs/backlog/PHASE_0_1_BACKLOG.md` Issue 09:

- Concurrent workers cannot claim the same task.
- Retries use exponential backoff with jitter.
- Stale running tasks can be recovered.
- Failed tasks enter a visible terminal state.
- Task payloads are versioned.
- Daily collection idempotency respects the user's timezone.
- Worker shutdown is graceful.

## Context and motivation

`backend/jose/services/tasks.py` and `backend/jose/models/core.py::Task` already implement a
simple polling queue: `enqueue_task`/`enqueue_collect_all` insert rows, `claim_next_task` pulls
the next eligible one, `run_task` executes it, `worker_loop` polls in a loop. Six of the seven
acceptance criteria are partially or fully unaddressed today:

- Concurrent claiming is *already correct* (`with_for_update(skip_locked=True)`) but untested.
- On failure, `run_task` immediately resets `status = "queued"` with no delay — a failing
  collector gets hammered in a tight retry loop with no backoff or jitter.
- A task stuck in `"running"` (worker crashed, OOM-killed, redeployed) has no path back to
  `"queued"` — it is lost forever.
- `Task.payload` has no version marker, so a payload shape change during a deploy would leave
  already-queued tasks uninterpretable with no way to detect the mismatch.
- `enqueue_collect_all`'s idempotency key uses `utcnow().date()` — UTC midnight, not the user's
  local day boundary — so "today's" collection run can fire at the wrong local time or double
  up near midnight UTC.
- `worker_loop` has no signal handling; a `SIGTERM` (redeploy, `docker stop`) kills it wherever
  it happens to be, mid-task-execution included.
- `worker_id` is a single static config string (`"jose-worker"`) shared by every process, so
  claimed/stale tasks can't be traced to the specific process that holds them.

This design closes all seven gaps by extending the existing table and services — no new
infrastructure, no new process, no Redis/message broker, consistent with CLAUDE.md's
inexpensive-infrastructure-first rule.

## Retry backoff with jitter

No new column. `run_task`'s failure branch currently does:

```python
task.status = "queued" if task.attempts < task.max_attempts else "failed"
```

This changes to also set `task.scheduled_at = utcnow() + backoff_delay(task.attempts)` when
requeuing, reusing the `scheduled_at` column `claim_next_task` already filters on
(`Task.scheduled_at <= utcnow()`) — so a backed-off task simply isn't eligible for claiming
until its delay elapses, with no change to the claim query itself.

`backoff_delay(attempts: int) -> timedelta` in `services/tasks.py`:

```
base = min(task_retry_base_seconds * (2 ** (attempts - 1)), task_retry_max_seconds)
jitter = base * task_retry_jitter_pct
delay = uniform(base - jitter, base + jitter)
```

New `Settings` fields: `task_retry_base_seconds: float = 60.0`,
`task_retry_max_seconds: float = 1800.0`, `task_retry_jitter_pct: float = 0.2`. With
`max_attempts = 3` (existing default), a task backs off ~60s then ~120s before its final
attempt fails it terminally.

## Stale running-task reaper

New `reap_stale_tasks(session: Session, threshold: timedelta) -> int` in `services/tasks.py`:

```sql
UPDATE tasks
SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
    scheduled_at = now()
WHERE status = 'running' AND started_at < now() - :threshold
```

Implemented as a single SQLAlchemy `update()` statement (not a select-then-loop), so it's one
indexed round trip (`ix_tasks_claim` already covers `status`) and race-free against a worker
that finishes the task in between. For every row it touches, emit a `SystemEvent`
(`event_type="task_reaped_stale"`, `entity_type="task"`, `entity_id=task.id`,
`data={"worker_id": ..., "attempts": ...}`) so recovery is auditable — matching the pattern in
`collection.py`/`job_merge.py`. Because `UPDATE ... RETURNING` gives back the affected rows in
one statement, no second query is needed to build these events.

Called from `worker_loop`, once per iteration, immediately before `claim_next_task` — cheap
(normally zero matching rows) so no separate cron job, scheduled task, or process is needed.
New `Settings.task_stale_running_minutes: float = 30.0` drives the threshold.

A task reaped after exhausting `max_attempts` goes straight to `"failed"` (skips a pointless
extra `"queued"` cycle) with a `SystemEvent` still recorded — satisfying both "stale tasks can
be recovered" and "failed tasks enter a visible terminal state" for this path.

## Worker identity and graceful shutdown

`worker_loop` stops reading `settings.worker_id` as the operational identity. Instead, at
startup it computes:

```python
worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:6]}"
```

This is what's written to `Task.worker_id` on claim and what appears in reaper `SystemEvent`s —
so a stale/orphaned task can be traced to the exact process that died holding it.
`settings.worker_id` is dropped (no consumer left).

Shutdown: `worker_loop` installs `signal.signal(signal.SIGTERM, ...)` and `SIGINT` handlers
that flip a module-level `threading.Event` (the loop is single-threaded, so a plain flag would
also work, but `Event` avoids relying on GIL semantics if that ever changes). Each iteration
checks the flag *before* calling `claim_next_task` — if set, the loop returns instead of
claiming. Because the check happens only between iterations, an in-flight `run_task()` call is
never interrupted; it always runs to its normal completion (success or caught exception) before
the loop re-checks the flag and exits. No new timeout or force-kill path is added — `run_task`
already wraps collection in `try`/`except`, so a slow collector delays shutdown but never hangs
it indefinitely beyond that call returning.

## Payload versioning

`Task` gains `payload_version: int` (default `1`, not null). `enqueue_task` gains a
`payload_version: int = 1` parameter, threaded through to the new column.
`enqueue_collect_all`'s `collect_source` tasks are version 1 (current shape:
`{"source_id": str}`). `run_task`'s dispatch stays a straight `task_type` match for now — there
is only one payload shape in the system today, so there's nothing to branch on yet — but the
column exists so a future payload shape change can be introduced behind a version check without
breaking tasks already queued (written by an older deploy) at the moment a new worker version
starts consuming them.

## Timezone-aware daily idempotency

`User` gains `timezone: str` (default `"America/Los_Angeles"`, not null) — an IANA zone name.

`enqueue_collect_all`'s `date_key` changes from:

```python
date_key = utcnow().date().isoformat()
```

to:

```python
date_key = datetime.now(ZoneInfo(user.timezone)).date().isoformat()
```

This is the only call site that reads `date_key`; `force=True` runs already bypass it with a
`uuid4()` suffix and are unaffected. No validation is added for `User.timezone` beyond what
`ZoneInfo` itself raises (`ZoneInfoNotFoundError` on a bad string) — it's a single-operator
field set by migration/admin, not user-facing input, so CLAUDE.md's external-boundary
validation rule doesn't apply here.

## Concurrent claim safety (test-only change)

`claim_next_task`'s `SELECT ... FOR UPDATE SKIP LOCKED` is already the correct primitive and is
left as-is. This design adds a test that runs two `claim_next_task` calls against overlapping
sessions against the same queued-task set and asserts they never return the same task id —
pinning behavior that today is implemented but unverified.

## Failed-task visibility (data-layer only)

`Task.status == "failed"` is already terminal and already queryable via the existing
`GET /api/v1/tasks`. The only change here is emitting a `SystemEvent`
(`event_type="task_failed"`, `entity_type="task"`, `entity_id=task.id`,
`data={"task_type": ..., "attempts": ..., "last_error": ...}`) in `run_task`'s failure branch
when a task transitions to `"failed"` (final attempt exhausted), so the terminal state is
audited, not just stored. No new UI, route, or dashboard field — Issue 10 (Source Health
dashboard) owns surfacing this to Scott.

## Data model changes (migration `0007_harden_task_queue`)

- `tasks.payload_version` — `Integer`, default `1`, not null.
- `users.timezone` — `String(50)`, default `"America/Los_Angeles"`, not null.

No changes to existing unique constraints or indexes. `ix_tasks_claim` already covers the
reaper's `status`/`started_at` lookup pattern well enough for expected table sizes (no new
index added; can revisit if `EXPLAIN` shows a problem at real volume).

## Settings changes

`backend/jose/config.py` gains:

- `task_retry_base_seconds: float = 60.0`
- `task_retry_max_seconds: float = 1800.0`
- `task_retry_jitter_pct: float = 0.2`
- `task_stale_running_minutes: float = 30.0`

`worker_id` is removed (superseded by the per-process identity computed in `worker_loop`).

## Testing plan

Fixture/unit tests only, no live network calls, in a new `backend/tests/test_tasks.py`:

- **Concurrent claim:** two claims against the same queued-task set never return the same task
  (pins existing `skip_locked` behavior).
- **Backoff math:** `backoff_delay` respects base/doubling/cap across several `attempts` values;
  jitter output stays within `[base - jitter, base + jitter]`.
- **Retry requeues with delay:** a failing task with `attempts < max_attempts` goes back to
  `"queued"` with `scheduled_at` in the future, and is *not* returned by `claim_next_task`
  until that time passes.
- **Terminal failure:** a failing task with `attempts == max_attempts` goes to `"failed"` and
  emits a `task_failed` `SystemEvent`.
- **Reaper reclaims:** a task in `"running"` with `started_at` older than the threshold is
  reclaimed to `"queued"` (attempts remaining) or `"failed"` (attempts exhausted), and emits a
  `task_reaped_stale` `SystemEvent` either way.
- **Reaper leaves fresh running tasks alone:** a `"running"` task with recent `started_at` is
  untouched.
- **Timezone idempotency:** two `enqueue_collect_all` calls for a user in a non-UTC zone, made
  on either side of UTC midnight but the same local day, produce the same idempotency key
  (second call returns no new task); a call made on the next local day produces a new key.
- **Payload version stamped:** `enqueue_collect_all`-created tasks carry `payload_version == 1`.
- **Worker identity uniqueness:** two `worker_loop`-style identity computations (same process)
  differ only if PID/hostname differ — covered indirectly by asserting the identity format
  contains hostname, pid, and a random suffix, rather than mocking process internals.
- **User isolation:** unaffected by this change (no cross-user query added) — no new isolation
  test needed beyond what `test_sources_service.py`/`test_job_dedup.py` already establish as
  the project's pattern.

## Out of scope

- Any dashboard/UI surfacing of failed or reaped tasks — Issue 10's Source Health dashboard.
- A heartbeat mechanism for stale detection — a fixed timeout since `started_at` is simpler,
  matches CLAUDE.md's inexpensive-infrastructure preference, and JOSE's task durations
  (collector runs) are short and bounded enough that a 30-minute default timeout is not a
  precision-sensitive value.
- Per-user configurable retry/backoff/stale-timeout values — these are operator-level tuning
  knobs (`Settings`), not user-facing preferences; only `timezone` is per-user because it's the
  one value that's inherently about the individual user's day boundary.
- Priority-queue changes, task cancellation, or a task history/audit UI beyond the
  `SystemEvent` rows already established as this project's audit mechanism.
