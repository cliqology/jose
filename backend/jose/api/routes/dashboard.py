from fastapi import APIRouter

from jose.api.deps import CurrentUser, DBSession
from jose.schemas import DashboardSummary
from jose.services.dashboard import get_dashboard_summary

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(db: DBSession, user: CurrentUser) -> DashboardSummary:
    return get_dashboard_summary(db, user)
