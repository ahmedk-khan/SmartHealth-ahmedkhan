import datetime
import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio import client as temporal_client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app import db as db_module
from app.core.exceptions import AppError
from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, BillingStatus, Patient, Slot, SlotStatus
from app.repositories.slots import SlotRepository
from app.workflows.temporal_logging import setup_activity_context, log_activity_step, log_activity_error
from app.core.settings import settings
from app.services.billing_checker import BillingChecker
from app.workflows.temporal_policies import BUSINESS_ACTIVITY_RETRY, COMPENSATION_RETRY, TRANSIENT_ACTIVITY_RETRY, WORKER_INTERRUPTION_RETRY


logger = logging.getLogger(__name__)


def _non_retryable(exc: AppError) -> ApplicationError:
    return ApplicationError(exc.message, type=exc.error_type, non_retryable=True)


@activity.defn
async def validate_appointment_data(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate appointment data: check patient and slot availability.
    
    Expects appointment_data to contain:
    - patient_id: ID of the patient
    - slot_id: ID of the slot
    - correlation_id (optional): Correlation ID for tracing
    - request_id (optional): Request ID for tracing
    """
    setup_activity_context(appointment_data, "validate_appointment_data")
    
    db: Session = db_module.SessionLocal()
    try:
        log_activity_step("Fetching patient", {"patient_id": appointment_data.get("patient_id")})
        patient = db.query(Patient).filter(Patient.id == appointment_data["patient_id"]).first()
        if not patient:
            raise AppError("Patient not found", status_code=404, error_type="not_found")

        log_activity_step("Fetching slot", {"slot_id": appointment_data.get("slot_id")})
        slot = db.query(Slot).filter(Slot.id == appointment_data["slot_id"]).first()
        if not slot:
            raise AppError("Slot not found", status_code=404, error_type="not_found")
        if slot.status != SlotStatus.AVAILABLE:
            raise AppError("Slot is no longer available", status_code=409, error_type="conflict")

        log_activity_step("Validation complete", {"provider_id": slot.provider_id, "service_id": slot.service_id})
        return {"patient_id": patient.id, "slot_id": slot.id, "provider_id": slot.provider_id, "service_id": slot.service_id}
    except AppError as exc:
        log_activity_error("validate_appointment_data", exc)
        raise _non_retryable(exc) from exc
    finally:
        db.close()


@activity.defn
async def wait_for_worker_interruption(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """Keep the demo booking pending until this worker is interrupted."""
    if activity.info().attempt > 1:
        return {"worker_restarted": True}
    while True:
        activity.heartbeat(appointment_data.get("slot_id"))
        await asyncio.sleep(1)


@activity.defn
async def reserve_slot(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """
    Reserve a slot for the appointment.
    
    Expects appointment_data to contain:
    - slot_id: ID of the slot to reserve
    - patient_id: ID of the patient reserving the slot
    - correlation_id (optional): Correlation ID for tracing
    - request_id (optional): Request ID for tracing
    """
    setup_activity_context(appointment_data, "reserve_slot")
    
    db: Session = db_module.SessionLocal()
    appointment_id: int | None = None
    try:
        log_activity_step("Fetching slot for reservation", {"slot_id": appointment_data.get("slot_id")})
        slot = db.query(Slot).filter(Slot.id == appointment_data["slot_id"]).first()
        if not slot:
            raise AppError("Slot not found", status_code=404, error_type="not_found")

        log_activity_step("Atomically reserving slot", {"slot_id": slot.id, "status": "RESERVED"})
        reserved = SlotRepository(db).reserve_for_patient(slot.id, appointment_data["patient_id"])
        if reserved is None:
            raise AppError("Slot is no longer available", status_code=409, error_type="conflict")
        
        logger.info("Slot reserved successfully", extra={"slot_id": reserved.id, "patient_id": reserved.patient_id})
        return {"slot_id": reserved.id, "patient_id": reserved.patient_id}
    except AppError as exc:
        log_activity_error("reserve_slot", exc)
        raise _non_retryable(exc) from exc
    finally:
        db.close()


@activity.defn
async def run_billing_precheck(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """
    Run billing precheck for the appointment.
    
    Expects appointment_data to contain:
    - appointment_id: ID of the appointment
    - correlation_id (optional): Correlation ID for tracing
    - request_id (optional): Request ID for tracing
    """
    setup_activity_context(appointment_data, "run_billing_precheck")
    
    db: Session = db_module.SessionLocal()
    try:
        log_activity_step("Checking existing billing", {"appointment_id": appointment_data.get("appointment_id")})
        appointment = db.query(Appointment).filter(Appointment.id == appointment_data["appointment_id"]).first()
        if not appointment:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")
        existing = db.query(Billing).filter(Billing.appointment_id == appointment.id).first()
        if existing:
            logger.info("Billing record already exists", extra={"appointment_id": appointment_data["appointment_id"], "status": existing.status.value})
            if existing.status != BillingStatus.APPROVED:
                raise AppError("Billing pre-check declined", status_code=402, error_type="billing_declined")
            return {"status": existing.status.value, "amount": float(existing.amount)}

        try:
            billing = BillingChecker(db).precheck(
                appointment,
                idempotency_key=appointment_data.get("idempotency_key"),
                force_failure=appointment_data.get("force_billing_failure"),
            )
        except IntegrityError:
            db.rollback()
            billing = db.query(Billing).filter(Billing.appointment_id == appointment_data["appointment_id"]).first()
            if billing is None:
                raise
        
        logger.info("Billing precheck approved", extra={"appointment_id": billing.appointment_id, "amount": float(billing.amount)})
        return {"status": billing.status.value, "amount": float(billing.amount)}
    except AppError as exc:
        log_activity_error("run_billing_precheck", exc)
        raise _non_retryable(exc) from exc
    except Exception as exc:
        log_activity_error("run_billing_precheck", exc)
        raise
    finally:
        db.close()


@activity.defn
async def create_pending_appointment(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "create_pending_appointment")
    db: Session = db_module.SessionLocal()
    try:
        existing_id = appointment_data.get("appointment_id")
        if existing_id:
            existing = db.query(Appointment).filter(Appointment.id == existing_id).first()
            if existing:
                return {"appointment_id": existing.id}
        booking_key = appointment_data.get("idempotency_key")
        if booking_key:
            existing = db.query(Appointment).filter(Appointment.booking_key == booking_key).first()
            if existing:
                return {"appointment_id": existing.id}
        appointment = Appointment(
            patient_id=appointment_data["patient_id"],
            provider_id=appointment_data["provider_id"],
            service_id=appointment_data["service_id"],
            slot_id=appointment_data["slot_id"],
            status=AppointmentStatus.REQUESTED,
            booking_key=booking_key,
        )
        db.add(appointment)
        db.flush()
        db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        from app.models.audit import AuditLog
        db.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="requested", after={"status": appointment.status.value}))
        db.commit()
        return {"appointment_id": appointment.id}
    finally:
        db.close()


@activity.defn
async def mark_slot_reserved(appointment_data: dict[str, Any]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        appointment = db.query(Appointment).filter(Appointment.id == appointment_data["appointment_id"]).first()
        if not appointment:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")
        if appointment.status == AppointmentStatus.REQUESTED:
            appointment.status = AppointmentStatus.SLOT_RESERVED
            appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
            db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
            from app.models.audit import AuditLog
            db.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="slot_reserved", after={"status": appointment.status.value}))
            db.commit()
        return {"status": appointment.status.value}
    finally:
        db.close()


@activity.defn
async def send_reminder(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """
    Send appointment reminder.
    
    Expects appointment_data to contain:
    - appointment_id: ID of the appointment
    - correlation_id (optional): Correlation ID for tracing
    - request_id (optional): Request ID for tracing
    """
    setup_activity_context(appointment_data, "send_reminder")
    
    from app.services.notification_service import NotificationService
    db = db_module.SessionLocal()
    try:
        notification = NotificationService(db).schedule_appointment_reminder(appointment_data["appointment_id"])
        return {"sent": False, "appointment_id": appointment_data["appointment_id"], "notification_id": notification.id}
    finally:
        db.close()


@activity.defn
async def cancel_reminder(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "cancel_reminder")
    notification_id = appointment_data.get("notification_id")
    if notification_id is None:
        return {"cancelled": True, "reason": "not_scheduled"}
    db = db_module.SessionLocal()
    try:
        from app.services.notification_service import NotificationService
        notification = NotificationService(db).cancel_notification(notification_id)
        return {"cancelled": notification is None or notification.status.value == "CANCELLED", "notification_id": notification_id}
    finally:
        db.close()


@activity.defn
async def confirm_appointment(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """
    Confirm the appointment and update its status.
    
    Expects appointment_data to contain:
    - appointment_id: ID of the appointment
    - correlation_id (optional): Correlation ID for tracing
    - request_id (optional): Request ID for tracing
    """
    setup_activity_context(appointment_data, "confirm_appointment")
    
    db: Session = db_module.SessionLocal()
    try:
        log_activity_step("Fetching appointment", {"appointment_id": appointment_data.get("appointment_id")})
        appointment = db.query(Appointment).filter(Appointment.id == appointment_data["appointment_id"]).first()
        if not appointment:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")
        
        log_activity_step("Updating appointment status to CONFIRMED", {"appointment_id": appointment.id})
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        from app.models.audit import AuditLog
        db.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="confirmed", after={"status": appointment.status.value}))
        db.commit()
        
        logger.info("Appointment confirmed", extra={"appointment_id": appointment.id, "status": appointment.status.value})
        return {"status": appointment.status.value}
    except AppError as exc:
        log_activity_error("confirm_appointment", exc)
        raise
    finally:
        db.close()


@activity.defn
async def release_slot(appointment_data: dict[str, Any]) -> dict[str, Any]:
    """
    Release a reserved slot back to available status.
    
    Expects appointment_data to contain:
    - slot_id: ID of the slot to release
    - correlation_id (optional): Correlation ID for tracing
    - request_id (optional): Request ID for tracing
    """
    setup_activity_context(appointment_data, "release_slot")
    
    db: Session = db_module.SessionLocal()
    try:
        log_activity_step("Releasing slot", {"slot_id": appointment_data.get("slot_id")})
        slot = db.query(Slot).filter(Slot.id == appointment_data["slot_id"]).first()
        if slot:
            appointment_id = appointment_data.get("appointment_id")
            if appointment_id is not None:
                appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
                if appointment and slot.patient_id != appointment.patient_id:
                    return {"slot_released": False, "reason": "slot_owned_by_another_patient"}
            slot.status = SlotStatus.AVAILABLE
            slot.patient_id = None
            slot.updated_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
            logger.info("Slot released", extra={"slot_id": slot.id})
        return {"slot_released": True}
    except Exception as exc:
        log_activity_error("release_slot", exc)
        raise
    finally:
        db.close()


@activity.defn
async def cancel_pending_appointment(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "cancel_pending_appointment")
    db: Session = db_module.SessionLocal()
    try:
        appointment = db.query(Appointment).filter(Appointment.id == appointment_data["appointment_id"]).first()
        if appointment and appointment.status in {AppointmentStatus.REQUESTED, AppointmentStatus.SLOT_RESERVED, AppointmentStatus.PENDING}:
            appointment.status = AppointmentStatus.CANCELLED
            appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
            db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
            from app.models.audit import AuditLog
            db.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="compensated", after={"status": appointment.status.value}))
            db.commit()
        return {"appointment_cancelled": appointment is not None}
    finally:
        db.close()


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

    db: Session = db_module.SessionLocal()
    appointment_id: int | None = None
    try:
        if appointment_data.get("force_failure"):
            raise RuntimeError("Simulated saga failure")

        appointment = Appointment(
            patient_id=validated["patient_id"],
            provider_id=validated["provider_id"],
            service_id=validated["service_id"],
            slot_id=validated["slot_id"],
            status=AppointmentStatus.REQUESTED,
            booking_key=appointment_data.get("idempotency_key"),
        )
        db.add(appointment)
        db.flush()
        db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
        from app.models.audit import AuditLog
        db.add(AuditLog(entity_type="appointment", entity_id=appointment.id, action="requested", after={"status": appointment.status.value}))
        db.commit()
        db.refresh(appointment)
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
                raise AppError("Slot is no longer available", status_code=409, error_type="conflict") from exc
            cause = getattr(cause, "cause", None)
        raise


async def start_appointment_saga(appointment_data: dict[str, Any]):
    try:
        client = await temporal_client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    except Exception as exc:
        raise AppError("Temporal workflow service is unavailable", status_code=503, error_type="workflow_unavailable") from exc
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
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )
    return handle
