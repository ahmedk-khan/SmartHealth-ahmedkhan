from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.authorization import require_permission, Permission
from app.core.dependencies import get_db
from app.models import User
from app.schemas.domain import PaginatedResponse, NotificationRead
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=PaginatedResponse[NotificationRead], summary="List user notifications")
def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.NOTIFICATION_READ)),
):
    """
    Retrieve in-app notifications for the authenticated user.
    """
    items, total = NotificationService(db).list_user_notifications(current_user.id, limit, offset)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)
