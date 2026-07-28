import uuid

from fastapi import APIRouter, HTTPException, Query, status

from jose.api.deps import CurrentUser, DBSession
from jose.models import Source
from jose.schemas import QueueResponse, SourceCreate, SourceRead, SourceUpdate
from jose.services import sources as sources_service
from jose.services.tasks import enqueue_task

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
def list_sources(db: DBSession, user: CurrentUser) -> list[Source]:
    return sources_service.list_sources(db, user)


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: DBSession, user: CurrentUser) -> Source:
    try:
        return sources_service.create_source(db, user, payload)
    except sources_service.DuplicateSourceUrlError as exc:
        raise HTTPException(status_code=409, detail="Source URL already exists") from exc


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: uuid.UUID, db: DBSession, user: CurrentUser) -> Source:
    try:
        return sources_service.get_source(db, user, source_id)
    except sources_service.SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(
    source_id: uuid.UUID, payload: SourceUpdate, db: DBSession, user: CurrentUser
) -> Source:
    try:
        return sources_service.update_source(db, user, source_id, payload)
    except sources_service.SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc
    except sources_service.DuplicateSourceUrlError as exc:
        raise HTTPException(status_code=409, detail="Source URL already exists") from exc


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: uuid.UUID,
    db: DBSession,
    user: CurrentUser,
    confirm: bool = Query(default=False),
) -> None:
    try:
        sources_service.delete_source(db, user, source_id, confirm=confirm)
    except sources_service.SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc
    except sources_service.DeleteConfirmationRequiredError as exc:
        raise HTTPException(
            status_code=400, detail="Deleting a source requires confirm=true"
        ) from exc


@router.post("/{source_id}/collect", response_model=QueueResponse)
def queue_source_collection(
    source_id: uuid.UUID, db: DBSession, user: CurrentUser
) -> QueueResponse:
    try:
        source = sources_service.get_source(db, user, source_id)
    except sources_service.SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc
    task = enqueue_task(
        db,
        user,
        task_type="collect_source",
        payload={"source_id": str(source.id)},
        idempotency_key=f"manual:{source.id}:{uuid.uuid4()}",
        priority=source.priority,
    )
    assert task is not None
    return QueueResponse(queued=1, task_ids=[task.id])
