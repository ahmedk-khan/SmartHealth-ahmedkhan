import logging
import uuid
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.client import WorkflowFailureError
from temporalio import client as temporal_client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from app.core.exceptions import AppError, ConflictError, ExternalServiceError
from app.core.settings import settings
from app.workers.temporal.policies import (
    BUSINESS_ACTIVITY_RETRY,
    COMPENSATION_RETRY,
    TRANSIENT_ACTIVITY_RETRY,
    WORKFLOW_RETRY,
)
from app.workers.temporal.activities.appointment_saga import (
    cancel_pending_appointment,
    cancel_reminder,
    confirm_appointment,
    create_pending_appointment,
    mark_slot_reserved,
    publish_appointment_created_event,
    release_slot,
    reserve_slot,
    run_billing_precheck,
    send_reminder,
    validate_appointment_data,
    _non_retryable,
)

logger = logging.getLogger(__name__)


@workflow.defn
class AppointmentSagaWorkflow:
    @workflow.run
    async def run(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        """
        Run the appointment booking saga workflow with correlation ID propagation.
        
        This workflow orchestrates the appointment booking process:
        1. Validate patient and slot data
        2. Reserve the slot
        3. Create appointment record
        4. Run billing precheck
        5. Send reminder
        6. Confirm appointment
        
        If any step fails, the slot is released.
        
        Args:
            appointment_data: Dictionary containing appointment details including
                            patient_id, slot_id, and optionally correlation_id and request_id
        """
        logger.info("Starting appointment saga workflow", extra={"appointment_data": appointment_data})

        if settings.booking_demo_pause_seconds:
            await workflow.sleep(settings.booking_demo_pause_seconds)
        
        try:
            # Ensure correlation_id is passed through all activities
            validated = await workflow.execute_activity(
                validate_appointment_data,
                appointment_data,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )

            await workflow.execute_activity(
                reserve_slot,
                {**appointment_data, **validated},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
        except Exception:
            if appointment_data.get("appointment_id"):
                await workflow.execute_activity(
                    cancel_pending_appointment,
                    appointment_data,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=COMPENSATION_RETRY,
                )
            raise

        created = await workflow.execute_activity(
            create_pending_appointment,
            {**appointment_data, **validated},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TRANSIENT_ACTIVITY_RETRY,
        )
        appointment_id = created["appointment_id"]
        await workflow.execute_activity(
            mark_slot_reserved,
            {**appointment_data, "appointment_id": appointment_id},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TRANSIENT_ACTIVITY_RETRY,
        )

        try:
            await workflow.execute_activity(
                run_billing_precheck,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=BUSINESS_ACTIVITY_RETRY,
            )
            reminder = await workflow.execute_activity(
                send_reminder,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            await workflow.execute_activity(
                confirm_appointment,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            event_result = await workflow.execute_activity(
                publish_appointment_created_event,
                {
                    **appointment_data,
                    "appointment_id": appointment_id,
                    **validated,
                    "status": "CONFIRMED",
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=TRANSIENT_ACTIVITY_RETRY,
            )
            if event_result.get("status") == "delivery_failed":
                raise RuntimeError("Appointment event was not published")
            logger.info("Appointment saga workflow completed successfully", extra={"appointment_id": appointment_id})
            return {"workflow_status": "CONFIRMED", "appointment_id": appointment_id}
        except Exception as exc:
            logger.error("Appointment saga workflow failed, releasing slot", extra={"appointment_id": appointment_id}, exc_info=True)
            await workflow.execute_activity(
                cancel_reminder,
                {**appointment_data, "appointment_id": appointment_id, "notification_id": reminder.get("notification_id") if "reminder" in locals() else None},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMPENSATION_RETRY,
            )
            await workflow.execute_activity(
                release_slot,
                {**appointment_data, "appointment_id": appointment_id, "slot_id": validated["slot_id"]},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMPENSATION_RETRY,
            )
            await workflow.execute_activity(
                cancel_pending_appointment,
                {**appointment_data, "appointment_id": appointment_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMPENSATION_RETRY,
            )
            raise


async def _run_appointment_saga_locally(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """
    Local (non-Temporal) fallback implementation of appointment saga.
    
    This runs when Temporal is unavailable, maintaining the same workflow logic.
    """
    logger.info("Running appointment saga locally (Temporal fallback)", extra={"appointment_data": appointment_data})
    
    validated = await validate_appointment_data(appointment_data)
    await reserve_slot({**appointment_data, **validated})

    from sqlalchemy.orm import Session
    from app import db as db_module
    from app.repositories import AppointmentRepository

    db: Session = db_module.SessionLocal()
    appointment_id: int | None = None
    try:
        if appointment_data.get("force_failure"):
            raise RuntimeError("Simulated saga failure")

        appointment = AppointmentRepository(db).create_requested({
            "patient_id": validated["patient_id"],
            "provider_id": validated["provider_id"],
            "service_id": validated["service_id"],
            "slot_id": validated["slot_id"],
            "idempotency_key": appointment_data.get("idempotency_key"),
        })
        appointment_id = appointment.id
        logger.info("Appointment record created (local)", extra={"appointment_id": appointment_id})
        await mark_slot_reserved({**appointment_data, "appointment_id": appointment_id})
    except Exception:
        await release_slot({**appointment_data, "appointment_id": appointment_id, "slot_id": validated["slot_id"]})
        if appointment_id is not None:
            await cancel_pending_appointment({**appointment_data, "appointment_id": appointment_id})
        raise
    finally:
        db.close()

    try:
        await run_billing_precheck({**appointment_data, "appointment_id": appointment_id})
        reminder = await send_reminder({**appointment_data, "appointment_id": appointment_id})
        await confirm_appointment({**appointment_data, "appointment_id": appointment_id})
        event_result = await publish_appointment_created_event({
            **appointment_data,
            "appointment_id": appointment_id,
            **validated,
            "status": "CONFIRMED",
        })
        if event_result.get("status") == "delivery_failed":
            raise RuntimeError("Appointment event was not published")
        logger.info("Appointment saga completed locally", extra={"appointment_id": appointment_id})
        return {"workflow_status": "CONFIRMED", "appointment_id": appointment_id}
    except Exception:
        await cancel_reminder({**appointment_data, "appointment_id": appointment_id, "notification_id": reminder.get("notification_id") if "reminder" in locals() else None})
        await release_slot({**appointment_data, "appointment_id": appointment_id, "slot_id": validated["slot_id"]})
        await cancel_pending_appointment({**appointment_data, "appointment_id": appointment_id})
        raise


async def run_appointment_saga(appointment_data: dict[str, Any]) -> dict[str, Any]:
    if settings.app_env == "local":
        return await _run_appointment_saga_locally(appointment_data)

    handle = await start_appointment_saga(appointment_data)
    try:
        return await handle.result()
    except WorkflowFailureError as exc:
        cause = exc.cause
        while cause is not None:
            if isinstance(cause, ApplicationError) and cause.type == "conflict":
                raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE") from exc
            cause = getattr(cause, "cause", None)
        raise


async def start_appointment_saga(appointment_data: dict[str, Any]):
    try:
        client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    except Exception as exc:
        raise ExternalServiceError("Temporal workflow service is unavailable", status_code=503, code="WORKFLOW_UNAVAILABLE") from exc
    workflow_id = appointment_data.get("workflow_id")
    if not workflow_id:
        idempotency_key = appointment_data.get("idempotency_key")
        workflow_id = (
            f"appointment-booking-{appointment_data['patient_id']}-{idempotency_key}"
            if idempotency_key
            else f"appointment-booking-{appointment_data['patient_id']}-{appointment_data['slot_id']}-{uuid.uuid4()}"
        )
    handle = await client.start_workflow(
        AppointmentSagaWorkflow.run,
        {**appointment_data, "workflow_id": workflow_id},
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
        execution_timeout=timedelta(minutes=settings.booking_workflow_timeout_minutes),
        retry_policy=WORKFLOW_RETRY,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )
    return handle
