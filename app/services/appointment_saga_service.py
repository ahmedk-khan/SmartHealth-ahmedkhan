"""Business logic for the appointment booking Temporal saga."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, NotFoundError, ValidationError
from app.models import AppointmentStatus, BillingStatus, SlotStatus
from app.repositories import AppointmentRepository, PatientRepository, SlotRepository
from app.services.billing_checker import BillingChecker
from app.services.healthcare_event_service import HealthcareEventService
from app.services.notification_service import NotificationService
from app.core.metrics import record_double_booking_prevented


class AppointmentSagaService:
    """Encapsulates booking saga steps so Temporal activities stay thin adapters."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.appointments = AppointmentRepository(db)
        self.patients = PatientRepository(db)
        self.slots = SlotRepository(db)

    def validate_booking(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        patient = self.patients.get_by_id(appointment_data["patient_id"])
        if not patient:
            raise NotFoundError("Patient not found", code="PATIENT_NOT_FOUND")

        slot = self.slots.get_by_id(appointment_data["slot_id"])
        if not slot:
            raise NotFoundError("Slot not found", code="SLOT_NOT_FOUND")
        if slot.status != SlotStatus.AVAILABLE:
            raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE")

        return {
            "patient_id": patient.id,
            "slot_id": slot.id,
            "provider_id": slot.provider_id,
            "service_id": slot.service_id,
        }

    def reserve_slot(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        slot = self.slots.get_by_id(appointment_data["slot_id"])
        if not slot:
            raise NotFoundError("Slot not found", code="SLOT_NOT_FOUND")

        reserved = self.slots.reserve_for_patient(slot.id, appointment_data["patient_id"])
        if reserved is None:
            record_double_booking_prevented()
            raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE")
        return {"slot_id": reserved.id, "patient_id": reserved.patient_id}

    def create_pending_appointment(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        existing_id = appointment_data.get("appointment_id")
        if existing_id:
            existing = self.appointments.get_by_id(existing_id)
            if existing:
                return {"appointment_id": existing.id}

        booking_key = appointment_data.get("idempotency_key")
        if booking_key:
            existing = self.appointments.get_by_booking_key(booking_key)
            if existing:
                return {"appointment_id": existing.id}

        appointment = self.appointments.create_requested(appointment_data)
        return {"appointment_id": appointment.id}

    def mark_slot_reserved(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        appointment = self.appointments.get_by_id(appointment_data["appointment_id"])
        if not appointment:
            raise NotFoundError("Appointment not found", code="APPOINTMENT_NOT_FOUND")
        if appointment.status == AppointmentStatus.REQUESTED:
            appointment = self.appointments.mark_slot_reserved(appointment.id)
        return {"status": appointment.status.value}

    def run_billing_precheck(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        appointment = self.appointments.get_by_id(appointment_data["appointment_id"])
        if not appointment:
            raise NotFoundError("Appointment not found", code="APPOINTMENT_NOT_FOUND")

        existing = self.appointments.get_billing_by_appointment_id(appointment.id)
        if existing:
            if existing.status != BillingStatus.APPROVED:
                raise ValidationError("Billing pre-check declined", code="BILLING_DECLINED")
            return {"status": existing.status.value, "amount": float(existing.amount)}

        try:
            billing = BillingChecker(self.db).precheck(
                appointment,
                idempotency_key=appointment_data.get("idempotency_key"),
                force_failure=appointment_data.get("force_billing_failure"),
            )
        except IntegrityError:
            self.appointments.rollback()
            billing = self.appointments.get_billing_by_appointment_id(appointment_data["appointment_id"])
            if billing is None:
                raise

        return {"status": billing.status.value, "amount": float(billing.amount)}

    def schedule_reminder(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        notification = NotificationService(self.db).schedule_appointment_reminder(
            appointment_data["appointment_id"]
        )
        return {
            "sent": False,
            "appointment_id": appointment_data["appointment_id"],
            "notification_id": notification.id,
        }

    def cancel_reminder(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        notification_id = appointment_data.get("notification_id")
        if notification_id is None:
            return {"cancelled": True, "reason": "not_scheduled"}

        notification = NotificationService(self.db).cancel_notification(notification_id)
        return {
            "cancelled": notification is None or notification.status.value == "CANCELLED",
            "notification_id": notification_id,
        }

    def confirm_appointment(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        appointment = self.appointments.get_by_id(appointment_data["appointment_id"])
        if not appointment:
            raise NotFoundError("Appointment not found", code="APPOINTMENT_NOT_FOUND")
        appointment = self.appointments.confirm(appointment.id)
        return {"status": appointment.status.value}

    async def publish_created_event(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        return await HealthcareEventService(self.db).publish_appointment_event_async(
            "appointment.created",
            appointment_id=appointment_data["appointment_id"],
            patient_id=appointment_data.get("patient_id"),
            provider_id=appointment_data.get("provider_id"),
            service_id=appointment_data.get("service_id"),
            slot_id=appointment_data.get("slot_id"),
            status=appointment_data.get("status"),
        )

    def release_slot(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        appointment_id = appointment_data.get("appointment_id")
        result, _released_slot_id = self.appointments.release_slot_for_appointment(
            appointment_data["slot_id"],
            appointment_id,
        )
        return result

    def cancel_pending_appointment(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "appointment_cancelled": self.appointments.cancel_pending(appointment_data["appointment_id"])
        }
