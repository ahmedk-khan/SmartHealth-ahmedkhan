import datetime
import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app import db as db_module
from app.core.exceptions import (
    AppError,
    NotFoundError,
    ConflictError,
    ValidationError,
    ExternalServiceError,
)
from app.models import Appointment, AppointmentStatus, Patient, Slot, SlotStatus, BillingStatus
from app.repositories import AppointmentRepository, PatientRepository, SlotRepository
from app.workers.temporal.logging import setup_activity_context, log_activity_step, log_activity_error
from app.core.settings import settings
from app.services.billing_checker import BillingChecker


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
        patient = PatientRepository(db).get_by_id(appointment_data["patient_id"])
        if not patient:
            raise NotFoundError("Patient not found")

        log_activity_step("Fetching slot", {"slot_id": appointment_data.get("slot_id")})
        slot = SlotRepository(db).get_by_id(appointment_data["slot_id"])
        if not slot:
            raise NotFoundError("Slot not found")
        if slot.status != SlotStatus.AVAILABLE:
            raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE")

        log_activity_step("Validation complete", {"provider_id": slot.provider_id, "service_id": slot.service_id})
        return {"patient_id": patient.id, "slot_id": slot.id, "provider_id": slot.provider_id, "service_id": slot.service_id}
    except AppError as exc:
        log_activity_error("validate_appointment_data", exc)
        raise _non_retryable(exc) from exc
    finally:
        db.close()


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
    try:
        log_activity_step("Fetching slot for reservation", {"slot_id": appointment_data.get("slot_id")})
        slot = SlotRepository(db).get_by_id(appointment_data["slot_id"])
        if not slot:
            raise NotFoundError("Slot not found")

        log_activity_step("Atomically reserving slot", {"slot_id": slot.id, "status": "RESERVED"})
        reserved = SlotRepository(db).reserve_for_patient(slot.id, appointment_data["patient_id"])
        if reserved is None:
            raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE")
        
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
        appointment_repository = AppointmentRepository(db)
        appointment = appointment_repository.get_by_id(appointment_data["appointment_id"])
        if not appointment:
            raise NotFoundError("Appointment not found")
        existing = appointment_repository.get_billing_by_appointment_id(appointment.id)
        if existing:
            logger.info("Billing record already exists", extra={"appointment_id": appointment_data["appointment_id"], "status": existing.status.value})
            if existing.status != BillingStatus.APPROVED:
                raise ValidationError("Billing pre-check declined", code="BILLING_DECLINED")
            return {"status": existing.status.value, "amount": float(existing.amount)}

        try:
            billing = BillingChecker(db).precheck(
                appointment,
                idempotency_key=appointment_data.get("idempotency_key"),
                force_failure=appointment_data.get("force_billing_failure"),
            )
        except IntegrityError:
            appointment_repository.rollback()
            billing = appointment_repository.get_billing_by_appointment_id(appointment_data["appointment_id"])
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
        appointment_repository = AppointmentRepository(db)
        existing_id = appointment_data.get("appointment_id")
        if existing_id:
            existing = appointment_repository.get_by_id(existing_id)
            if existing:
                return {"appointment_id": existing.id}
        booking_key = appointment_data.get("idempotency_key")
        if booking_key:
            existing = appointment_repository.get_by_booking_key(booking_key)
            if existing:
                return {"appointment_id": existing.id}
        appointment = appointment_repository.create_requested(appointment_data)
        return {"appointment_id": appointment.id}
    finally:
        db.close()


@activity.defn
async def mark_slot_reserved(appointment_data: dict[str, Any]) -> dict[str, Any]:
    db: Session = db_module.SessionLocal()
    try:
        appointment_repository = AppointmentRepository(db)
        appointment = appointment_repository.get_by_id(appointment_data["appointment_id"])
        if not appointment:
            raise NotFoundError("Appointment not found")
        if appointment.status == AppointmentStatus.REQUESTED:
            appointment = appointment_repository.mark_slot_reserved(appointment.id)
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
        appointment_repository = AppointmentRepository(db)
        appointment = appointment_repository.get_by_id(appointment_data["appointment_id"])
        if not appointment:
            raise NotFoundError("Appointment not found")
        
        log_activity_step("Updating appointment status to CONFIRMED", {"appointment_id": appointment.id})
        appointment = appointment_repository.confirm(appointment.id)
        
        logger.info("Appointment confirmed", extra={"appointment_id": appointment.id, "status": appointment.status.value})
        return {"status": appointment.status.value}
    except AppError as exc:
        log_activity_error("confirm_appointment", exc)
        raise
    finally:
        db.close()


@activity.defn
async def publish_appointment_created_event(appointment_data: dict[str, Any]) -> dict[str, Any]:
    setup_activity_context(appointment_data, "publish_appointment_created_event")
    db: Session = db_module.SessionLocal()
    try:
        from app.services.healthcare_event_service import HealthcareEventService

        return HealthcareEventService(db).publish_appointment_event(
            "appointment.created",
            appointment_id=appointment_data["appointment_id"],
            patient_id=appointment_data.get("patient_id"),
            provider_id=appointment_data.get("provider_id"),
            service_id=appointment_data.get("service_id"),
            slot_id=appointment_data.get("slot_id"),
            status=appointment_data.get("status"),
        )
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
        appointment_id = appointment_data.get("appointment_id")
        result, released_slot_id = AppointmentRepository(db).release_slot_for_appointment(appointment_data["slot_id"], appointment_id)
        if released_slot_id is not None:
            logger.info("Slot released", extra={"slot_id": released_slot_id})
        return result
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
        appointment_repository = AppointmentRepository(db)
        return {"appointment_cancelled": appointment_repository.cancel_pending(appointment_data["appointment_id"])}
    finally:
        db.close()
