import uuid
from datetime import timedelta
from typing import Any

from temporalio import client as temporal_client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.core.exceptions import AppError
from app.core.settings import settings
from app.workflows.temporal_policies import WORKFLOW_RETRY
from app.models import Provider, ServiceStatus, User, UserRole, provider_services
from app.repositories import ServiceRepository
from app.services.base import BaseService
from app.services.healthcare_event_service import HealthcareEventService
from app.workflows.service_publish import ServicePublishWorkflow, chunk_service, embed_chunks, mark_published, structure_service, validate_service


_LOCAL_PUBLISH_WORKFLOWS: dict[str, dict[str, Any]] = {}


class _LocalWorkflowHandle:
    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.run_id = str(uuid.uuid4())

    async def query(self, query_name: str) -> Any:
        if query_name == "publish_progress":
            return _LOCAL_PUBLISH_WORKFLOWS[self.workflow_id]
        if query_name != "publish_status":
            raise AppError("Unsupported query", status_code=400, error_type="invalid_query")
        return _LOCAL_PUBLISH_WORKFLOWS[self.workflow_id]["status"]


class ServiceManagementService(BaseService):
    def __init__(self, db):
        super().__init__(db)
        self.repository = ServiceRepository(db)

    def create_service(self, payload, current_user: User):
        if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
        if not self.repository.department_exists(payload.department_id):
            raise AppError("Department not found", status_code=404, error_type="not_found")
        service_data = payload.model_dump()
        # Publication is a Temporal workflow; creation can only produce a draft.
        service_data["is_published"] = False
        service_data["status"] = ServiceStatus.DRAFT
        provider = None
        if current_user.role == UserRole.provider:
            provider = self.db.query(Provider).filter(Provider.user_id == current_user.id).first()
            if not provider:
                provider = Provider(user_id=current_user.id)
                self.db.add(provider)
                self.db.flush()
        created = self.repository.create_service(service_data)
        if provider:
            self.db.execute(provider_services.insert().values(provider_id=provider.id, service_id=created.id))
            self.db.commit()
            self.db.refresh(created)
        HealthcareEventService().publish_service_event("service.created", service_id=created.id, department_id=created.department_id, status=created.status.value)
        return created

    def update_service(self, service_id: int, payload, current_user: User):
        if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
        service = self.repository.get_by_id(service_id)
        if not service:
            raise AppError("Service not found", status_code=404, error_type="not_found")
        self._ensure_provider_service_access(service, current_user)
        if not self.repository.department_exists(payload.department_id):
            raise AppError("Department not found", status_code=404, error_type="not_found")
        data = payload.model_dump()
        data["status"] = service.status if payload.is_published else ServiceStatus.DRAFT
        return self.repository.update_service(service, data)

    async def publish_service(self, service_id: int, current_user: User):
        if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
        service = self.repository.get_by_id(service_id)
        if not service:
            raise AppError("Service not found", status_code=404, error_type="not_found")
        if current_user.role == UserRole.provider:
            provider = self.db.query(Provider).filter(Provider.user_id == current_user.id).first()
            if not provider or not provider.specialty or not provider.department_id:
                raise AppError(
                    "Complete your provider profile before publishing a service",
                    status_code=409,
                    error_type="provider_profile_incomplete",
                )
        self._ensure_provider_service_access(service, current_user)
        if service.status == ServiceStatus.PUBLISHED:
            raise AppError("Service is already published", status_code=409, error_type="conflict")
        if service.status == ServiceStatus.PUBLISHING:
            raise AppError("Service publish is already in progress", status_code=409, error_type="conflict")
        if service.status == ServiceStatus.UNPUBLISHING:
            raise AppError("Service cannot be published while unpublishing", status_code=409, error_type="conflict")

        workflow_id = f"service-publish-{service.id}"
        try:
            client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        except Exception as exc:
            if settings.app_env.lower() in {"local", "test", "development"}:
                handle = await self._start_local_publish_workflow(service.id, workflow_id)
                return {"workflow_id": workflow_id, "run_id": handle.run_id}
            raise AppError("Temporal workflow service is unavailable", status_code=503, error_type="workflow_unavailable") from exc
        try:
            handle = await client.start_workflow(
                ServicePublishWorkflow.run,
                service.id,
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
                execution_timeout=timedelta(minutes=settings.temporal_workflow_timeout_minutes),
                retry_policy=WORKFLOW_RETRY,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(workflow_id)
        return {"workflow_id": workflow_id, "run_id": handle.run_id}

    def unpublish_service(self, service_id: int, current_user: User):
        if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
        service = self.repository.get_by_id(service_id)
        if not service:
            raise AppError("Service not found", status_code=404, error_type="not_found")
        self._ensure_provider_service_access(service, current_user)
        if service.status != ServiceStatus.PUBLISHED:
            raise AppError("Service is not published", status_code=409, error_type="conflict")
        unpublished = self.repository.unpublish(service)
        HealthcareEventService().publish_service_event("service.unpublished", service_id=unpublished.id, department_id=unpublished.department_id, status=unpublished.status.value)
        return unpublished

    async def publish_status(self, service_id: int, current_user: User):
        service = self.repository.get_by_id(service_id)
        if not service:
            raise AppError("Service not found", status_code=404, error_type="not_found")
        self._ensure_provider_service_access(service, current_user)
        workflow_id = f"service-publish-{service.id}"
        try:
            client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
            handle = client.get_workflow_handle(workflow_id)
            progress = await handle.query("publish_progress")
            if isinstance(progress, str):
                return {"workflow_id": workflow_id, "status": progress}
            return {"workflow_id": workflow_id, **progress}
        except Exception as exc:
            if workflow_id in _LOCAL_PUBLISH_WORKFLOWS:
                return {"workflow_id": workflow_id, **_LOCAL_PUBLISH_WORKFLOWS[workflow_id]}
            if "not found" in str(exc).lower() or "workflow could not be found" in str(exc).lower():
                if service.status == ServiceStatus.PUBLISHED:
                    return {"workflow_id": workflow_id, "status": ServiceStatus.PUBLISHED.value}
                raise AppError("Publish workflow not found", status_code=404, error_type="workflow_not_found")
            raise

    def _ensure_provider_service_access(self, service, current_user: User) -> None:
        if current_user.role != UserRole.provider:
            return
        provider = self.db.query(Provider).filter(Provider.user_id == current_user.id).first()
        if not provider or not self.db.query(provider_services).filter(
            provider_services.c.provider_id == provider.id,
            provider_services.c.service_id == service.id,
        ).first():
            raise AppError("Forbidden", status_code=403, error_type="forbidden")

    async def _start_local_publish_workflow(self, service_id: int, workflow_id: str) -> _LocalWorkflowHandle:
        _LOCAL_PUBLISH_WORKFLOWS[workflow_id] = {
            "status": ServiceStatus.PUBLISHING.value,
            "stage": "VALIDATING",
            "chunks_total": 0,
            "embeddings_generated": 0,
            "run_id": str(uuid.uuid4()),
        }
        try:
            published = await validate_service(service_id)
            if published["status"] == ServiceStatus.PUBLISHED.value:
                _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
                _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["stage"] = "COMPLETE"
                return _LocalWorkflowHandle(workflow_id)

            service_struct = await structure_service(published["service"])
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["stage"] = "CHUNKING"
            chunks = await chunk_service(service_struct)
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id].update({"stage": "EMBEDDING", "chunks_total": len(chunks)})
            embedded_chunks = await embed_chunks(chunks)
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id].update({"stage": "PERSISTING", "embeddings_generated": len(embedded_chunks)})
            await mark_published({"service_id": service_id, "chunks": embedded_chunks})
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["stage"] = "COMPLETE"
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
            return _LocalWorkflowHandle(workflow_id)
        except Exception as exc:
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = "FAILED"
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["error"] = str(exc)
            raise
