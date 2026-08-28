import logging
import asyncio

from temporalio import client, worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from app.core.settings import settings
from app.temporal.activities import (
    cancel_pending_appointment,
    cancel_reminder,
    chunk_service,
    confirm_appointment,
    create_pending_appointment,
    embed_chunks,
    mark_published,
    mark_publish_failed,
    mark_slot_reserved,
    release_slot,
    reserve_slot,
    run_billing_precheck,
    send_reminder,
    structure_service,
    validate_appointment_data,
    validate_service,
    wait_for_worker_interruption,
)
from app.workflows import AppointmentSagaWorkflow, ServicePublishWorkflow


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
                mark_published,
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
            ],
        )
        await temporal_worker.run()

    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
