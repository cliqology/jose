import os
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jose.collectors.base import CollectedJob, CollectionResult
from jose.config import get_settings
from jose.db.session import SessionLocal
from jose.models import SystemEvent, Task
from jose.schemas import SourceCreate
from jose.services import tasks as tasks_module
from jose.services.sources import create_source
from jose.services.tasks import (
    backoff_delay,
    claim_next_task,
    enqueue_collect_all,
    enqueue_task,
    reap_stale_tasks,
    run_task,
    worker_loop,
)


class _FailingCollector:
    def __init__(self, message: str) -> None:
        self._message = message

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        raise RuntimeError(self._message)


class _FakeCollector:
    def __init__(self, jobs: list[CollectedJob]) -> None:
        self._jobs = jobs

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        return CollectionResult(jobs=self._jobs, rejected_count=0)


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


def test_run_task_does_not_overwrite_a_task_reaped_out_from_under_it(db_session, user):
    task = enqueue_task(
        db_session,
        user,
        task_type="unsupported_test_type",
        payload={},
        idempotency_key="ownership-guard-1",
    )
    claimed = claim_next_task(db_session, "worker-a")

    # Simulate the reaper claiming this row out from under worker-a while it's "in flight".
    task.status = "failed"
    task.worker_id = None
    db_session.commit()

    run_task(db_session, claimed)

    db_session.refresh(task)
    assert task.status == "failed"


def test_enqueue_task_can_stamp_a_non_default_payload_version(db_session, user):
    task = enqueue_task(
        db_session,
        user,
        task_type="collect_source",
        payload={"source_id": "abc"},
        idempotency_key="payload-version-explicit",
        payload_version=2,
    )
    assert task.payload_version == 2


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


def test_collect_source_task_does_not_count_failure_until_final_attempt(
    db_session, user, monkeypatch
):
    source = create_source(
        db_session,
        user,
        SourceCreate(name="Flaky Task", url="https://flaky-task.example.com/jobs"),
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector("boom"),
    )
    task = enqueue_task(
        db_session,
        user,
        task_type="collect_source",
        payload={"source_id": str(source.id)},
        idempotency_key="retry-consecutive-1",
    )
    task.max_attempts = 2
    db_session.commit()

    # Attempt 1 of 2: this failure will be automatically retried, so it must not
    # count against consecutive_failures yet.
    claimed = claim_next_task(db_session, "test-worker")
    run_task(db_session, claimed)
    db_session.refresh(task)
    db_session.refresh(source)
    assert task.status == "queued"
    assert task.attempts == 1
    assert source.consecutive_failures == 0

    # The requeue schedules a future retry via backoff; pull it back so the test
    # doesn't have to sleep through the delay.
    task.scheduled_at = datetime.now(UTC)
    db_session.commit()

    # Attempt 2 of 2: this is the final attempt, so the task fails terminally and
    # the failure should now count.
    claimed = claim_next_task(db_session, "test-worker")
    run_task(db_session, claimed)
    db_session.refresh(task)
    db_session.refresh(source)
    assert task.status == "failed"
    assert task.attempts == 2
    assert source.consecutive_failures == 1


def test_collect_source_task_success_after_retry_resets_consecutive_failures(
    db_session, user, monkeypatch
):
    source = create_source(
        db_session,
        user,
        SourceCreate(name="Recovering Task", url="https://recovering-task.example.com/jobs"),
    )
    task = enqueue_task(
        db_session,
        user,
        task_type="collect_source",
        payload={"source_id": str(source.id)},
        idempotency_key="retry-consecutive-2",
    )
    task.max_attempts = 3
    db_session.commit()

    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector("boom"),
    )
    claimed = claim_next_task(db_session, "test-worker")
    run_task(db_session, claimed)
    db_session.refresh(task)
    db_session.refresh(source)
    assert task.status == "queued"
    assert task.attempts == 1
    assert source.consecutive_failures == 0

    # The requeue schedules a future retry via backoff; pull it back so the test
    # doesn't have to sleep through the delay.
    task.scheduled_at = datetime.now(UTC)
    db_session.commit()

    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://recovering-task.example.com/apply/1",
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FakeCollector([job]),
    )
    claimed = claim_next_task(db_session, "test-worker")
    run_task(db_session, claimed)
    db_session.refresh(task)
    db_session.refresh(source)
    assert task.status == "completed"
    assert task.attempts == 2
    assert task.attempts < task.max_attempts
    assert source.consecutive_failures == 0


def test_task_last_error_is_sanitized(db_session, user, monkeypatch):
    source = create_source(
        db_session, user, SourceCreate(name="Leaky Task", url="https://leaky-task.example.com/jobs")
    )
    monkeypatch.setattr(
        "jose.services.collection.get_collector",
        lambda url, adapter: _FailingCollector("failed: token=sk-live-abc123"),
    )
    task = enqueue_task(
        db_session,
        user,
        task_type="collect_source",
        payload={"source_id": str(source.id)},
        idempotency_key="sanitize-task-error-1",
    )
    task.max_attempts = 1
    db_session.commit()

    claimed = claim_next_task(db_session, "test-worker")
    run_task(db_session, claimed)

    db_session.refresh(task)
    assert task.status == "failed"
    assert task.last_error is not None
    assert "sk-live-abc123" not in task.last_error
    assert "[redacted]" in task.last_error
