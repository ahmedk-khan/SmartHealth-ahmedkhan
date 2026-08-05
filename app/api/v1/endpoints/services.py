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
from app.workflows.service_publish import ServicePublishWorkflow

router = APIRouter(prefix="/services", tags=["services"])


@router.post("", response_model=ServiceRead, status_code=status.HTTP_200_OK)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")
    if not db.query(Department).filter(Department.id == payload.department_id).first():
        raise ValueError("Department not found")
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
        raise PermissionError("Forbidden")
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise ValueError("Service not found")
    if service.status == ServiceStatus.PUBLISHED:
        raise AppError("Service is already published", status_code=409, error_type="conflict")
    if service.status == ServiceStatus.PUBLISHING:
        raise AppError("Service publish is already in progress", status_code=409, error_type="conflict")
    if service.status == ServiceStatus.UNPUBLISHING:
        raise AppError("Service cannot be published while unpublishing", status_code=409, error_type="conflict")

    workflow_id = f"service-publish-{service.id}"
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


@router.post("/{service_id}/unpublish", status_code=status.HTTP_200_OK)
def unpublish_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise ValueError("Service not found")
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
        raise ValueError("Service not found")
    workflow_id = f"service-publish-{service.id}"
    client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    handle = client.get_workflow_handle(workflow_id)
    try:
        status_value = await handle.query("publish_status")
        return {"workflow_id": workflow_id, "status": status_value}
    except Exception as exc:
        if "not found" in str(exc).lower() or "workflow could not be found" in str(exc).lower():
            raise AppError("Publish workflow not found", status_code=404, error_type="workflow_not_found")
        raise


@router.get("", response_model=PaginatedResponse[ServiceRead])
def list_services(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Service).filter(Service.is_published.is_(True))
    total = query.count()
    items = query.order_by(Service.id).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}
