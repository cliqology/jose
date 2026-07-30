from datetime import UTC, datetime

from sqlalchemy import select

from jose.config import get_settings
from jose.models import SystemEvent, Task
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
