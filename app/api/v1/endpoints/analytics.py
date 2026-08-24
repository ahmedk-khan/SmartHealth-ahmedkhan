from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models import User
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/summary",
    summary="Analytics summary",
    description="Returns current dashboard metrics and high-level operational analytics for the platform.",
)
def get_analytics_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, object]:
    service = AnalyticsService(db)
    del current_user
    return service.get_dashboard_metrics()


@router.get(
    "/reconcile",
    summary="Reconcile analytics",
    description="Runs a reconciliation pass to verify analytics data consistency and sync state across the system.",
)
def reconcile_analytics(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, object]:
    service = AnalyticsService(db)
    del current_user
    return service.reconcile_metrics()
