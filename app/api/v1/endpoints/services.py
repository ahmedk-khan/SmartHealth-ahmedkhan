import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from temporalio import client as temporal_client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.core.settings import settings
from app.models import Department, Service, ServiceStatus, User, UserRole
from app.schemas.domain import PaginatedResponse, ServiceCreate, ServiceRead
from app.workflows.service_publish import ServicePublishWorkflow, chunk_service, mark_published, structure_service, validate_service

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
        await mark_published(service_id, chunks)
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
        return _LocalWorkflowHandle(workflow_id)
    except Exception as exc:
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = "FAILED"
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["error"] = str(exc)
        raise


@router.post("", response_model=ServiceRead, status_code=status.HTTP_200_OK)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    if not db.query(Department).filter(Department.id == payload.department_id).first():
        raise AppError("Department not found", status_code=404, error_type="not_found")
    service_data = payload.model_dump()
    if service_data.get("is_published"):
        service_data["status"] = ServiceStatus.PUBLISHED
    else:
        service_data["status"] = ServiceStatus.DRAFT
    service = Service(**service_data)
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


@router.post("/{service_id}/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise AppError("Service not found", status_code=404, error_type="not_found")
    if service.status == ServiceStatus.PUBLISHED:
        raise AppError("Service is already published", status_code=409, error_type="conflict")
    if service.status == ServiceStatus.PUBLISHING:
        raise AppError("Service publish is already in progress", status_code=409, error_type="conflict")
    if service.status == ServiceStatus.UNPUBLISHING:
        raise AppError("Service cannot be published while unpublishing", status_code=409, error_type="conflict")

    workflow_id = f"service-publish-{service.id}"
    try:
        client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        try:
            handle = await client.start_workflow(
                ServicePublishWorkflow.run,
                service.id,
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(workflow_id)
        return {"workflow_id": workflow_id, "run_id": handle.run_id}
    except Exception:
        handle = await _start_local_publish_workflow(service.id, workflow_id)
        return {"workflow_id": workflow_id, "run_id": handle.run_id}


@router.post("/{service_id}/unpublish", status_code=status.HTTP_200_OK)
def unpublish_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise AppError("Service not found", status_code=404, error_type="not_found")
    if service.status != ServiceStatus.PUBLISHED:
        raise AppError("Service is not published", status_code=409, error_type="conflict")
    service.status = ServiceStatus.UNPUBLISHED
    service.is_published = False
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


@router.get("/{service_id}/publish-status")
async def publish_status(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise AppError("Service not found", status_code=404, error_type="not_found")
    workflow_id = f"service-publish-{service.id}"
    try:
        client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        handle = client.get_workflow_handle(workflow_id)
        status_value = await handle.query("publish_status")
        return {"workflow_id": workflow_id, "status": status_value}
    except Exception as exc:
        if workflow_id in _LOCAL_PUBLISH_WORKFLOWS:
            return {"workflow_id": workflow_id, "status": _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"]}
        if "not found" in str(exc).lower() or "workflow could not be found" in str(exc).lower():
            if service.status == ServiceStatus.PUBLISHED:
                return {"workflow_id": workflow_id, "status": ServiceStatus.PUBLISHED.value}
            raise AppError("Publish workflow not found", status_code=404, error_type="workflow_not_found")
        raise


@router.get("", response_model=PaginatedResponse[ServiceRead])
def list_services(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Service).filter(Service.is_published.is_(True))
    total = query.count()
    items = query.order_by(Service.id).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}
