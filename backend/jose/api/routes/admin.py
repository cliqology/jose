from fastapi import APIRouter, Header, HTTPException

from jose.api.deps import CurrentUser, DBSession
from jose.config import get_settings
from jose.schemas import QueueResponse
from jose.services.tasks import enqueue_collect_all

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/collect-all", response_model=QueueResponse)
def collect_all(
    db: DBSession,
    user: CurrentUser,
    authorization: str | None = Header(default=None),
) -> QueueResponse:
    expected = f"Bearer {get_settings().jose_scheduler_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid scheduler token")
    tasks = enqueue_collect_all(db, user)
    return QueueResponse(queued=len(tasks), task_ids=[task.id for task in tasks])
