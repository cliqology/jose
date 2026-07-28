from fastapi import APIRouter
from sqlalchemy import text

from jose.api.deps import DBSession

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: DBSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "jose-api"}
