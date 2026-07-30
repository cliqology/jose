import os
import random
import signal
import socket
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jose.config import get_settings
from jose.db.session import SessionLocal
from jose.models import Source, SystemEvent, Task, User
from jose.services.collection import collect_source


def utcnow() -> datetime:
    return datetime.now(UTC)


def enqueue_task(
    session: Session,
    user: User,
    task_type: str,
    payload: dict,
    idempotency_key: str,
    priority: int = 100,
) -> Task | None:
    task = Task(
        user_id=user.id,
        task_type=task_type,
        payload=payload,
        priority=priority,
        idempotency_key=idempotency_key,
    )
    session.add(task)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return None
    session.refresh(task)
    return task


def enqueue_collect_all(session: Session, user: User, force: bool = False) -> list[Task]:
    sources = session.scalars(
        select(Source)
        .where(Source.user_id == user.id, Source.enabled.is_(True))
        .order_by(Source.priority, Source.name)
    ).all()
    date_key = datetime.now(ZoneInfo(user.timezone)).date().isoformat()
    tasks: list[Task] = []
    for source in sources:
        suffix = str(uuid.uuid4()) if force else date_key
        task = enqueue_task(
            session,
            user,
            task_type="collect_source",
            payload={"source_id": str(source.id)},
            idempotency_key=f"collect_source:{source.id}:{suffix}",
            priority=source.priority,
        )
        if task:
            tasks.append(task)
    return tasks


def claim_next_task(session: Session, worker_id: str) -> Task | None:
    task = session.scalar(
        select(Task)
        .where(Task.status == "queued", Task.scheduled_at <= utcnow())
        .order_by(Task.priority, Task.scheduled_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not task:
        return None
    task.status = "running"
    task.started_at = utcnow()
    task.worker_id = worker_id
    task.attempts += 1
    session.commit()
    session.refresh(task)
    return task


def backoff_delay(attempts: int) -> timedelta:
    settings = get_settings()
    base = min(
        settings.task_retry_base_seconds * (2 ** (attempts - 1)),
        settings.task_retry_max_seconds,
    )
    jitter = base * settings.task_retry_jitter_pct
    seconds = random.uniform(base - jitter, base + jitter)
    return timedelta(seconds=seconds)


def run_task(session: Session, task: Task) -> None:
    try:
        if task.task_type == "collect_source":
            collect_source(session, uuid.UUID(task.payload["source_id"]))
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")
        task = session.get(Task, task.id)
        if task:
            task.status = "completed"
            task.completed_at = utcnow()
            task.last_error = None
            session.commit()
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
