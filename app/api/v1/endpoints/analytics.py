from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin_or_front_desk
from app.models import User
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/summary",
    summary="Analytics summary",
    description="Returns current dashboard metrics and high-level operational analytics for the platform.",
)
def get_analytics_summary(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_front_desk),
) -> dict[str, object]:
    service = AnalyticsService(db)
    return service.get_dashboard_metrics(start_date, end_date)


@router.get(
    "/reconcile",
    summary="Reconcile analytics",
    description="Runs a reconciliation pass to verify analytics data consistency and sync state across the system.",
)
def reconcile_analytics(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_front_desk)) -> dict[str, object]:
    service = AnalyticsService(db)
    return service.reconcile_metrics()
