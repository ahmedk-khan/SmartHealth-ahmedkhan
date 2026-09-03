"""Client-side helpers for appointment booking workflows (non-deterministic I/O)."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from temporalio import client as temporal_client
from temporalio.client import WorkflowFailureError
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from app.core.exceptions import AppError, ConflictError, ExternalServiceError
from app.core.settings import settings
from app.workers.temporal.policies import WORKFLOW_RETRY
from app.workers.temporal.workflows.appointment_saga import AppointmentSagaWorkflow

logger = logging.getLogger(__name__)


def _local_fallback_allowed() -> bool:
    return settings.app_env.lower() in {"local", "test", "development", "dev"}


def _should_force_failure(appointment_data: dict[str, Any]) -> bool:
    return bool(appointment_data.get("force_failure") or settings.booking_force_failure)


def _reraise_activity_error(exc: Exception) -> None:
    """Map Temporal activity failures back to HTTP-friendly domain errors."""
    if isinstance(exc, ApplicationError):
        if exc.type == "conflict":
            raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE") from exc
        raise AppError(
            str(exc),
            status_code=409 if exc.type == "conflict" else 500,
            error_type=exc.type or "workflow_error",
        ) from exc
    if isinstance(exc, AppError):
        raise
    raise exc


async def _run_appointment_saga_locally(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the booking saga inline when Temporal is unavailable (local dev only)."""
    from app.workers.temporal.activities.appointment_saga import (
        cancel_pending_appointment,
        cancel_reminder,
        confirm_appointment,
        mark_slot_reserved,
        publish_appointment_created_event,
        release_slot,
        reserve_slot,
        run_billing_precheck,
        send_reminder,
        validate_appointment_data,
    )

    logger.info("Running appointment saga locally (Temporal fallback)", extra={"appointment_data": appointment_data})

    try:
        validated = await validate_appointment_data(appointment_data)
        await reserve_slot({**appointment_data, **validated})

        from sqlalchemy.orm import Session

        from app import db as db_module
        from app.repositories import AppointmentRepository

        db: Session = db_module.SessionLocal()
        appointment_id: int | None = None
        reminder: dict[str, Any] | None = None
        try:
            if _should_force_failure(appointment_data):
                raise RuntimeError("Simulated saga failure")

            appointment = AppointmentRepository(db).create_requested(
                {
                    "patient_id": validated["patient_id"],
                    "provider_id": validated["provider_id"],
                    "service_id": validated["service_id"],
                    "slot_id": validated["slot_id"],
                    "idempotency_key": appointment_data.get("idempotency_key"),
                }
            )
            appointment_id = appointment.id
            await mark_slot_reserved({**appointment_data, "appointment_id": appointment_id})
        except Exception:
            await release_slot(
                {**appointment_data, "appointment_id": appointment_id, "slot_id": validated["slot_id"]}
            )
            if appointment_id is not None:
                await cancel_pending_appointment({**appointment_data, "appointment_id": appointment_id})
            raise
        finally:
            db.close()

        try:
            await run_billing_precheck({**appointment_data, "appointment_id": appointment_id})
            reminder = await send_reminder({**appointment_data, "appointment_id": appointment_id})
            await confirm_appointment({**appointment_data, "appointment_id": appointment_id})
            event_result = await publish_appointment_created_event(
                {
                    **appointment_data,
                    "appointment_id": appointment_id,
                    **validated,
                    "status": "CONFIRMED",
                }
            )
            if event_result.get("status") == "delivery_failed":
                logger.warning(
                    "Appointment confirmed; event queued in outbox after Kafka delivery failure",
                    extra={"appointment_id": appointment_id},
                )
            return {"workflow_status": "CONFIRMED", "appointment_id": appointment_id}
        except Exception:
            await cancel_reminder(
                {
                    **appointment_data,
                    "appointment_id": appointment_id,
                    "notification_id": reminder.get("notification_id") if reminder else None,
                }
            )
            await release_slot(
                {**appointment_data, "appointment_id": appointment_id, "slot_id": validated["slot_id"]}
            )
            await cancel_pending_appointment({**appointment_data, "appointment_id": appointment_id})
            raise
    except Exception as exc:
        _reraise_activity_error(exc)
        raise  # pragma: no cover


async def start_appointment_saga(appointment_data: dict[str, Any]):
    """Start the booking workflow and return its handle without awaiting completion."""
    try:
        client = await temporal_client.Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
    except Exception as exc:
        if _local_fallback_allowed():
            logger.info("Temporal unavailable; running appointment saga locally", extra={"appointment_data": appointment_data})
            result = await _run_appointment_saga_locally(appointment_data)

            class _LocalHandle:
                async def result(self_inner):
                    return result

            return _LocalHandle()
        raise ExternalServiceError(
            "Temporal workflow service is unavailable",
            status_code=503,
            code="WORKFLOW_UNAVAILABLE",
        ) from exc

    workflow_id = appointment_data.get("workflow_id")
    if not workflow_id:
        idempotency_key = appointment_data.get("idempotency_key")
        workflow_id = (
            f"appointment-booking-{appointment_data['patient_id']}-{idempotency_key}"
            if idempotency_key
            else f"appointment-booking-{appointment_data['patient_id']}-{appointment_data['slot_id']}-{uuid.uuid4()}"
        )

    return await client.start_workflow(
        AppointmentSagaWorkflow.run,
        {
            **appointment_data,
            "workflow_id": workflow_id,
            "force_failure": _should_force_failure(appointment_data),
        },
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
        execution_timeout=timedelta(minutes=settings.booking_workflow_timeout_minutes),
        retry_policy=WORKFLOW_RETRY,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )


async def run_appointment_saga(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """Run the booking saga to completion (local inline fallback or Temporal)."""
    try:
        handle = await start_appointment_saga(appointment_data)
    except ExternalServiceError:
        if _local_fallback_allowed():
            return await _run_appointment_saga_locally(appointment_data)
        raise

    try:
        return await handle.result()
    except WorkflowFailureError as exc:
        cause = exc.cause
        while cause is not None:
            if isinstance(cause, ApplicationError) and cause.type == "conflict":
                raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE") from exc
            cause = getattr(cause, "cause", None)
        raise
