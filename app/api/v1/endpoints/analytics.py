from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
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
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    service = AnalyticsService(db)
    if current_user.role.value not in {"admin", "front_desk"}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    try:
        return service.get_dashboard_metrics(start_date, end_date)
    except ValueError as exc:
        raise AppError("Invalid analytics date range", status_code=400, error_type="validation_error") from exc


@router.get(
    "/reconcile",
    summary="Reconcile analytics",
    description="Runs a reconciliation pass to verify analytics data consistency and sync state across the system.",
)
def reconcile_analytics(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, object]:
    service = AnalyticsService(db)
    if current_user.role.value not in {"admin", "front_desk"}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    return service.reconcile_metrics()
