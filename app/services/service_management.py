import uuid
from typing import Any, TYPE_CHECKING

from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.authorization import Permission, ServiceOwnershipGuard
from app.core.authorization.service import check_permission
from app.models import ServiceStatus, User, UserRole
from app.repositories import ProviderRepository, ServiceRepository
from app.services.base import BaseService
from app.services.healthcare_event_service import HealthcareEventService

if TYPE_CHECKING:
    from app.services.adapters import WorkflowOrchestratorAdapter


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
    def __init__(self, db, orchestrator: "WorkflowOrchestratorAdapter | None" = None):
        super().__init__(db)
        self.repository = ServiceRepository(db)
        self.providers = ProviderRepository(db)
        self._orchestrator = orchestrator

    def create_service(self, payload, current_user: User):
        check_permission(current_user, Permission.SERVICE_CREATE)
        if not self.repository.department_exists(payload.department_id):
            raise NotFoundError("Department not found", code="DEPARTMENT_NOT_FOUND")
        service_data = payload.model_dump()
        requested_provider_id = service_data.pop("provider_id", None)
        # Publication is a Temporal workflow; creation can only produce a draft.
        service_data["is_published"] = False
        service_data["status"] = ServiceStatus.DRAFT

        if current_user.role == UserRole.provider:
            provider = self.providers.get_or_create_for_user(current_user.id)
            if requested_provider_id is not None and requested_provider_id != provider.id:
                raise ForbiddenError("Providers may only create services for themselves")
        else:
            if requested_provider_id is None:
                raise ValidationError(
                    "provider_id is required when creating a service",
                    code="PROVIDER_REQUIRED",
                )
            provider = self.providers.get_by_id(requested_provider_id)
            if provider is None:
                raise NotFoundError("Provider not found", code="PROVIDER_NOT_FOUND")

        created = self.repository.create_service(service_data)
        self.providers.link_service_and_commit(provider, created.id)
        self.repository.refresh(created)
        HealthcareEventService(self.db).publish_service_event("service.created", service_id=created.id, department_id=created.department_id, status=created.status.value)
        return created

    def get_service(self, service_id: int, current_user: User):
        """Fetch a single service by ID with role-aware visibility."""
        check_permission(current_user, Permission.SERVICE_READ)
        service = self.repository.get_by_id(service_id)
        if not service:
            raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
        # Patients can only see published services
        if current_user.role == UserRole.patient and not service.is_published:
            raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
        self.log_info(
            "Service fetched",
            operation="get_service",
            data={"service_id": service_id, "role": current_user.role},
        )
        return service

    def list_services(
        self,
        offset: int,
        limit: int,
        current_user: User,
        search: str | None = None,
        department_id: int | None = None,
    ):
        """Return paginated services. Patients only see published; staff see all."""
        check_permission(current_user, Permission.SERVICE_READ)
        if current_user.role in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            if current_user.role == UserRole.provider:
                provider = self.providers.get_by_user_id(current_user.id)
                if provider is None:
                    return [], 0
                items, total = self.providers.list_services(provider.id, offset=offset, limit=limit)
            else:
                items, total = self.repository.list_all(offset=offset, limit=limit)
        else:
            items, total = self.repository.list_published(
                offset=offset, limit=limit, search=search, department_id=department_id
            )
        self.log_info("Services listed", operation="list_services", data={"total": total})
        return items, total

    def update_service(self, service_id: int, payload, current_user: User):
        service = self.repository.get_by_id(service_id)
        if not service:
            raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
        ServiceOwnershipGuard(current_user, service).enforce()
        if not self.repository.department_exists(payload.department_id):
            raise NotFoundError("Department not found", code="DEPARTMENT_NOT_FOUND")
        data = payload.model_dump()
        data.pop("provider_id", None)
        data.pop("is_published", None)
        return self.repository.update_service(service, data)

    async def publish_service(self, service_id: int, current_user: User):
        service = self.repository.get_by_id(service_id)
        if not service:
            raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
        if current_user.role == UserRole.provider:
            provider = self.providers.get_by_user_id(current_user.id)
            if not provider or not provider.specialty or not provider.department_id:
                raise AppError(
                    "Complete your provider profile before publishing a service",
                    status_code=409,
                    error_type="provider_profile_incomplete",
                    code="PROVIDER_PROFILE_INCOMPLETE",
                )
        ServiceOwnershipGuard(current_user, service).enforce()
        if service.status == ServiceStatus.PUBLISHED:
            raise ConflictError("Service is already published", code="SERVICE_ALREADY_PUBLISHED")
        if service.status == ServiceStatus.PUBLISHING:
            raise ConflictError("Service publish is already in progress", code="SERVICE_PUBLISHING")
        if service.status == ServiceStatus.UNPUBLISHING:
            raise ConflictError("Service cannot be published while unpublishing", code="SERVICE_UNPUBLISHING")

        # Use injected orchestrator if available, otherwise lazy-load Temporal
        if self._orchestrator:
            workflow_id = f"service-publish-{service.id}"
            return await self._orchestrator.start_service_publish_workflow(service_id, workflow_id)
        
        # Fallback: lazy-load Temporal (for backward compatibility)
        from temporalio import client as temporal_client
        from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError
        from app.workers.temporal.workflows.service_publish import ServicePublishWorkflow
        from app.workers.temporal.policies import WORKFLOW_RETRY
        from app.core.settings import settings
        from datetime import timedelta
        
        workflow_id = f"service-publish-{service.id}"
        try:
            client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        except Exception as exc:
            if settings.app_env.lower() in {"local", "test", "development"}:
                handle = await self._start_local_publish_workflow(service.id, workflow_id)
                return {"workflow_id": workflow_id, "run_id": handle.run_id}
            raise AppError("Temporal workflow service is unavailable", status_code=503, error_type="workflow_unavailable", code="TEMPORAL_UNAVAILABLE") from exc
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
        service = self.repository.get_by_id(service_id)
        if not service:
            raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
        ServiceOwnershipGuard(current_user, service).enforce()
        if service.status != ServiceStatus.PUBLISHED:
            raise ConflictError("Service is not published", code="SERVICE_NOT_PUBLISHED")
        unpublished = self.repository.unpublish(service)
        HealthcareEventService(self.db).publish_service_event("service.unpublished", service_id=unpublished.id, department_id=unpublished.department_id, status=unpublished.status.value)
        return unpublished

    async def publish_status(self, service_id: int, current_user: User):
        service = self.repository.get_by_id(service_id)
        if not service:
            raise NotFoundError("Service not found", code="SERVICE_NOT_FOUND")
        ServiceOwnershipGuard(current_user, service).enforce()
        workflow_id = f"service-publish-{service.id}"
        
        # Use injected orchestrator if available
        if self._orchestrator:
            return await self._orchestrator.get_workflow_status(workflow_id)
        
        # Fallback: lazy-load Temporal
        from temporalio import client as temporal_client
        from app.core.settings import settings
        
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
                raise NotFoundError("Publish workflow not found", code="WORKFLOW_NOT_FOUND")
            raise

    async def _start_local_publish_workflow(self, service_id: int, workflow_id: str) -> "_LocalWorkflowHandle":
        # Lazy import to avoid circular dependencies
        from app.workers.temporal.activities.service_publish import (
            chunk_service,
            embed_chunks,
            publish_service_published_event,
            structure_service,
            validate_service,
        )
        
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
            await publish_service_published_event({"service_id": service_id, "chunks": embedded_chunks})
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["stage"] = "COMPLETE"
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = ServiceStatus.PUBLISHED.value
            return _LocalWorkflowHandle(workflow_id)
        except Exception as exc:
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["status"] = "FAILED"
            _LOCAL_PUBLISH_WORKFLOWS[workflow_id]["error"] = str(exc)
            raise
