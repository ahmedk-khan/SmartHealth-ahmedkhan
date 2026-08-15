from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def get_analytics_summary(db: Session = Depends(get_db)) -> dict[str, object]:
    service = AnalyticsService(db)
    return service.get_dashboard_metrics()


@router.get("/reconcile")
def reconcile_analytics(db: Session = Depends(get_db)) -> dict[str, object]:
    service = AnalyticsService(db)
    return service.reconcile_metrics()
