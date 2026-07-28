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
    date_key = utcnow().date().isoformat()
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
            task.status = "queued" if task.attempts < task.max_attempts else "failed"
            session.commit()


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
