import logging
import asyncio

from temporalio import client, worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from app.core.settings import settings
from app.workers.temporal.activities.appointment_saga import (
    cancel_pending_appointment,
    confirm_appointment,
    create_pending_appointment,
    mark_slot_reserved,
    release_slot,
    run_billing_precheck,
    reserve_slot,
    send_reminder,
    cancel_reminder,
    validate_appointment_data,
    publish_appointment_created_event,
    wait_for_worker_interruption,
)
from app.workers.temporal.activities.service_publish import (
    chunk_service,
    embed_chunks,
    mark_publish_failed,
    publish_service_published_event,
    structure_service,
    validate_service,
)
from app.workers.temporal.workflows.appointment_saga import AppointmentSagaWorkflow
from app.workers.temporal.workflows.service_publish import ServicePublishWorkflow


logger = logging.getLogger(__name__)


def main() -> None:
    async def run_worker() -> None:
        backoff_seconds = 2
        while True:
            try:
                temporal_client = await client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
                break
            except Exception as exc:
                logger.warning(
                    "Temporal is not ready yet, retrying worker connect",
                    extra={"temporal_host": settings.temporal_host, "error": str(exc)},
                )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 10)

        temporal_worker = worker.Worker(
            temporal_client,
            workflow_runner=SandboxedWorkflowRunner(
                restrictions=SandboxRestrictions.default.with_passthrough_modules(
                    "numpy",
                    "pgvector",
                    "sqlalchemy",
                    "httpx",
                ),
            ),
            task_queue=settings.temporal_task_queue,
            workflows=[ServicePublishWorkflow, AppointmentSagaWorkflow],
            activities=[
                validate_service,
                structure_service,
                chunk_service,
                embed_chunks,
                publish_service_published_event,
                mark_slot_reserved,
                mark_publish_failed,
                validate_appointment_data,
                reserve_slot,
                run_billing_precheck,
                send_reminder,
                cancel_reminder,
                confirm_appointment,
                release_slot,
                cancel_pending_appointment,
                create_pending_appointment,
                wait_for_worker_interruption,
                publish_appointment_created_event,
            ],
        )
        await temporal_worker.run()

    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
