from fastapi import APIRouter
from sqlalchemy import select

from jose.api.deps import CurrentUser, DBSession
from jose.models import Task
from jose.schemas import TaskRead

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def list_tasks(db: DBSession, user: CurrentUser) -> list[Task]:
    return list(
        db.scalars(
            select(Task)
            .where(Task.user_id == user.id)
            .order_by(Task.created_at.desc())
            .limit(200)
        ).all()
    )
