import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from temporalio import client as temporal_client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.models import ServiceStatus, User, UserRole
from app.schemas.domain import PaginatedResponse, ServiceCreate, ServiceRead
from app.services import ServiceManagementService

router = APIRouter(prefix="/services", tags=["services"])

_LOCAL_PUBLISH_WORKFLOWS: dict[str, dict[str, Any]] = {}


class _LocalWorkflowHandle:
    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.run_id = str(uuid.uuid4())

    async def query(self, query_name: str) -> str:
        if query_name != "publish_status":
            raise AppError("Unsupported query", status_code=400, error_type="invalid_query")
        return _LOCAL_PUBLISH_WORKFLOWS[self.workflow_id]["status"]


async def _start_local_publish_workflow(service_id: int, workflow_id: str) -> _LocalWorkflowHandle:
    _LOCAL_PUBLISH_WORKFLOWS[workflow_id] = {"status": ServiceStatus.PUBLISHING.value, "run_id": str(uuid.uuid4())}
    try:
        published = await validate_service(service_id)
        if published["status"] == ServiceStatus.PUBLISHED.value:
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
            return _LocalWorkflowHandle(workflow_id)

        service_struct = await structure_service(published["service"])
        chunks = await chunk_service(service_struct)
        await mark_published({"service_id": service_id, "chunks": chunks})
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
        return _LocalWorkflowHandle(workflow_id)
    except Exception as exc:
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = "FAILED"
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["error"] = str(exc)
        raise


@router.post(
    "",
    response_model=ServiceRead,
    status_code=status.HTTP_200_OK,
    summary="Create service",
    description="Creates a healthcare service definition for provider and departmental catalog usage.",
)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ServiceManagementService(db)
    return service.create_service(payload, current_user)


@router.put("/{service_id}", response_model=ServiceRead)
def update_service(service_id: int, payload: ServiceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ServiceManagementService(db)
    return service.update_service(service_id, payload, current_user)


@router.post(
    "/{service_id}/publish",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish service",
    description="Publishes a service to the public catalog and starts the service publication workflow.",
)
async def publish_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ServiceManagementService(db)
    return await service.publish_service(service_id, current_user)


@router.post(
    "/{service_id}/unpublish",
    status_code=status.HTTP_200_OK,
    summary="Unpublish service",
    description="Removes a service from the public-facing catalog while preserving the underlying record.",
)
def unpublish_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ServiceManagementService(db)
    return service.unpublish_service(service_id, current_user)


@router.get(
    "/{service_id}/publish-status",
    summary="Get publish status",
    description="Checks the current state of a service publication workflow and returns the latest status.",
)
async def publish_status(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ServiceManagementService(db)
    return await service.publish_status(service_id, current_user)


@router.get(
    "",
    response_model=PaginatedResponse[ServiceRead],
    summary="List services",
    description="Returns a paginated list of available services for operational and customer-facing use.",
)
def list_services(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ServiceManagementService(db)
    if current_user.role in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        items, total = service.repository.list_all(offset=offset, limit=limit)
    else:
        items, total = service.repository.list_published(offset=offset, limit=limit)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
