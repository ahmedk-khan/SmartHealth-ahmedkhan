"""
Concrete implementations of adapter interfaces for Temporal and Kafka.

These adapters encapsulate all worker-layer dependencies and are injected
into the API layer, keeping services completely decoupled from worker specifics.
"""

from typing import Any
from datetime import timedelta
import logging

from app.core.exceptions import ExternalServiceError, AppError
from app.core.settings import settings
from app.services.adapters import WorkflowOrchestratorAdapter, EventPublisherAdapter

logger = logging.getLogger(__name__)


class TemporalWorkflowOrchestrator(WorkflowOrchestratorAdapter):
    """Temporal implementation of workflow orchestration."""
    
    async def start_service_publish_workflow(self, service_id: int, workflow_id: str) -> dict[str, Any]:
        """Start a service publication workflow via Temporal."""
        try:
            from temporalio import client as temporal_client
            from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
            from temporalio.exceptions import WorkflowAlreadyStartedError
            from app.workers.temporal.workflows.service_publish import ServicePublishWorkflow
            from app.workers.temporal.policies import WORKFLOW_RETRY
            
            try:
                client = await temporal_client.Client.connect(
                    settings.temporal_host, 
                    namespace=settings.temporal_namespace
                )
            except Exception as exc:
                if settings.app_env.lower() in {"local", "test", "development"}:
                    logger.info("Temporal unavailable, falling back to local workflow", extra={"service_id": service_id})
                    from app.workers.temporal.runtime.service_publish import run_service_publish_locally

                    handle = await run_service_publish_locally(service_id, workflow_id)
                    return {"workflow_id": workflow_id, "run_id": handle.run_id}
                
                raise ExternalServiceError(
                    "Temporal workflow service is unavailable", 
                    status_code=503, 
                    code="TEMPORAL_UNAVAILABLE"
                ) from exc
            
            try:
                handle = await client.start_workflow(
                    ServicePublishWorkflow.run,
                    service_id,
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
        except AppError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error starting workflow", extra={"service_id": service_id})
            raise AppError("Failed to start workflow", status_code=500) from exc
    
    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        """Get the current status of a workflow."""
        try:
            from temporalio import client as temporal_client
            
            client = await temporal_client.Client.connect(
                settings.temporal_host, 
                namespace=settings.temporal_namespace
            )
            handle = client.get_workflow_handle(workflow_id)
            progress = await handle.query("publish_progress")
            
            if isinstance(progress, str):
                return {"workflow_id": workflow_id, "status": progress}
            return {"workflow_id": workflow_id, **progress}
        except Exception as exc:
            from app.workers.temporal.runtime.service_publish import get_local_publish_progress

            local_progress = get_local_publish_progress(workflow_id)
            if local_progress is not None:
                return {"workflow_id": workflow_id, **local_progress}
            logger.exception("Error querying workflow status", extra={"workflow_id": workflow_id})
            raise ExternalServiceError("Failed to query workflow status", status_code=503) from exc
    
    async def run_appointment_saga(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        """Run an appointment booking saga via Temporal."""
        from app.workers.temporal.runtime.appointment_booking import run_appointment_saga
        return await run_appointment_saga(appointment_data)


class KafkaEventPublisher(EventPublisherAdapter):
    """Kafka implementation of event publishing."""
    
    async def publish_appointment_created(self, **metadata) -> dict[str, Any]:
        """Publish appointment created event to Kafka."""
        from app.workers.kafka.producer import EventPublisher
        publisher = EventPublisher()
        await publisher.publish("appointment.created", **metadata)
        return {"status": "published"}
    
    async def publish_service_event(self, event_type: str, **metadata) -> dict[str, Any]:
        """Publish service event to Kafka."""
        from app.workers.kafka.producer import EventPublisher
        publisher = EventPublisher()
        await publisher.publish(event_type, **metadata)
        return {"status": "published"}
