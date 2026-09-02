from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.authorization import require_permission, Permission, ServiceOwnershipGuard
from app.core.exceptions import NotFoundError
from app.models import User
from app.repositories import ServiceRepository
from app.schemas.domain import PaginatedResponse, ServiceCreate, ServiceRead, SlotRead
from app.services import ServiceManagementService, SlotService

router = APIRouter(prefix="/services", tags=["services"])


@router.post(
    "",
    response_model=ServiceRead,
    status_code=status.HTTP_200_OK,
    summary="Create service",
    description="Creates a healthcare service definition for provider and departmental catalog usage.",
)
def create_service(
    payload: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SERVICE_CREATE)),
):
    svc = ServiceManagementService(db)
    return svc.create_service(payload, current_user)


@router.put(
    "/{service_id}",
    response_model=ServiceRead,
    summary="Update service",
    description="Updates an existing service definition. Providers may only update their own services.",
)
def update_service(
    service_id: int,
    payload: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SERVICE_UPDATE)),
):
    # Ownership guard: Ensure user can modify this service
    service = ServiceRepository(db).get_by_id(service_id)
    if not service:
        raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
    ServiceOwnershipGuard(current_user, service).enforce()
    
    svc = ServiceManagementService(db)
    return svc.update_service(service_id, payload, current_user)


@router.post(
    "/{service_id}/publish",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish service",
    description="Publishes a service to the public catalog and starts the service publication workflow.",
)
async def publish_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SERVICE_PUBLISH)),
):
    # Ownership guard: Ensure user can publish this service
    service = ServiceRepository(db).get_by_id(service_id)
    if not service:
        raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
    ServiceOwnershipGuard(current_user, service).enforce()
    
    svc = ServiceManagementService(db)
    return await svc.publish_service(service_id, current_user)


@router.post(
    "/{service_id}/unpublish",
    status_code=status.HTTP_200_OK,
    summary="Unpublish service",
    description="Removes a service from the public-facing catalog while preserving the underlying record.",
)
def unpublish_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SERVICE_UNPUBLISH)),
):
    # Ownership guard: Ensure user can unpublish this service
    service = ServiceRepository(db).get_by_id(service_id)
    if not service:
        raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
    ServiceOwnershipGuard(current_user, service).enforce()
    
    svc = ServiceManagementService(db)
    return svc.unpublish_service(service_id, current_user)


@router.get(
    "/{service_id}/publish-status",
    summary="Get publish status",
    description="Checks the current state of a service publication workflow and returns the latest status.",
)
async def publish_status(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SERVICE_PUBLISH)),
):
    # Ownership guard: Ensure user can view this service's publish status
    service = ServiceRepository(db).get_by_id(service_id)
    if not service:
        raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
    ServiceOwnershipGuard(current_user, service).enforce()
    
    svc = ServiceManagementService(db)
    return await svc.publish_status(service_id, current_user)


@router.get(
    "/{service_id}/slots",
    response_model=PaginatedResponse[SlotRead],
    summary="List slots for a service",
    description="Returns all availability slots associated with a specific service. Patients see AVAILABLE only; staff/providers see all.",
)
def list_slots_by_service(
    service_id: int,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SLOT_READ)),
):
    slot_svc = SlotService(db)
    items, total = slot_svc.list_slots_by_service(
        service_id=service_id, offset=offset, limit=limit, current_user=current_user
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{service_id}",
    response_model=ServiceRead,
    summary="Get service by ID",
    description="Returns a single service detail. Patients may only view published services.",
)
def get_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SERVICE_READ)),
):
    svc = ServiceManagementService(db)
    return svc.get_service(service_id, current_user)


@router.get(
    "",
    response_model=PaginatedResponse[ServiceRead],
    summary="List services",
    description="Returns a paginated list of services. Patients see published only; staff and providers see all.",
)
def list_services(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query(None, description="Optional name search (patients only)"),
    department_id: int = Query(None, description="Filter by department (patients only)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SERVICE_READ)),
):
    svc = ServiceManagementService(db)
    items, total = svc.list_services(
        offset=offset,
        limit=limit,
        current_user=current_user,
        search=search,
        department_id=department_id,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}
