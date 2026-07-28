from io import BytesIO

from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy import select

from jose.api.deps import CurrentUser, DBSession
from jose.models import SourceImportRun
from jose.schemas import ImportPreviewRead, ImportRowOutcomeRead, ImportRunRead
from jose.services.source_import import classify_workbook, commit_import, summarize

router = APIRouter(prefix="/api/v1/sources/import", tags=["sources"])


@router.post("/preview", response_model=ImportPreviewRead)
async def preview_import_endpoint(
    db: DBSession, user: CurrentUser, file: UploadFile = File(...)  # noqa: B008
) -> ImportPreviewRead:
    content = await file.read()
    outcomes = classify_workbook(db, user, BytesIO(content))
    counts = summarize(outcomes)
    return ImportPreviewRead(
        filename=file.filename or "upload.xlsx",
        created=counts["create"],
        updated=counts["update"],
        skipped=counts["skip"],
        flagged=counts["flag"],
        rows=[
            ImportRowOutcomeRead(
                row_number=o.row_number,
                name=o.name,
                url=o.url,
                category=o.category,
                action=o.action,
                reason=o.reason,
            )
            for o in outcomes
            if o.action != "skip"
        ],
    )


@router.post("/commit", response_model=ImportRunRead, status_code=status.HTTP_201_CREATED)
async def commit_import_endpoint(
    db: DBSession, user: CurrentUser, file: UploadFile = File(...)  # noqa: B008
) -> SourceImportRun:
    content = await file.read()
    return commit_import(
        db, user, BytesIO(content), filename=file.filename or "upload.xlsx"
    )


@router.get("/runs", response_model=list[ImportRunRead])
def list_import_runs(db: DBSession, user: CurrentUser) -> list[SourceImportRun]:
    return list(
        db.scalars(
            select(SourceImportRun)
            .where(SourceImportRun.user_id == user.id)
            .order_by(SourceImportRun.completed_at.desc())
        ).all()
    )
