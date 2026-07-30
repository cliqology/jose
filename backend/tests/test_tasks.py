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
