from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.authorization import require_permission, Permission
from app.models import User, UserRole
from app.schemas.domain import PaginatedResponse, ServiceCreate, ServiceRead
from app.services import ServiceManagementService

router = APIRouter(prefix="/services", tags=["services"])

@router.post(
    "",
    response_model=ServiceRead,
    status_code=status.HTTP_200_OK,
    summary="Create service",
    description="Creates a healthcare service definition for provider and departmental catalog usage.",
)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SERVICE_CREATE))):
    service = ServiceManagementService(db)
    return service.create_service(payload, current_user)


@router.put("/{service_id}", response_model=ServiceRead)
def update_service(service_id: int, payload: ServiceCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SERVICE_UPDATE))):
    service = ServiceManagementService(db)
    return service.update_service(service_id, payload, current_user)


@router.post(
    "/{service_id}/publish",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish service",
    description="Publishes a service to the public catalog and starts the service publication workflow.",
)
async def publish_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SERVICE_PUBLISH))):
    service = ServiceManagementService(db)
    return await service.publish_service(service_id, current_user)


@router.post(
    "/{service_id}/unpublish",
    status_code=status.HTTP_200_OK,
    summary="Unpublish service",
    description="Removes a service from the public-facing catalog while preserving the underlying record.",
)
def unpublish_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SERVICE_UNPUBLISH))):
    service = ServiceManagementService(db)
    return service.unpublish_service(service_id, current_user)


@router.get(
    "/{service_id}/publish-status",
    summary="Get publish status",
    description="Checks the current state of a service publication workflow and returns the latest status.",
)
async def publish_status(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SERVICE_PUBLISH))):
    service = ServiceManagementService(db)
    return await service.publish_status(service_id, current_user)


@router.get(
    "",
    response_model=PaginatedResponse[ServiceRead],
    summary="List services",
    description="Returns a paginated list of available services for operational and customer-facing use.",
)
def list_services(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SERVICE_READ))):
    service = ServiceManagementService(db)
    if current_user.role in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        items, total = service.repository.list_all(offset=offset, limit=limit)
    else:
        items, total = service.repository.list_published(offset=offset, limit=limit)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
