from typing import Optional
import time

from fastapi import Header

from app.core.exceptions import AppError
from app.core.idempotency import idempotency_store
from app.core.metrics import (
    record_appointment_created,
    record_appointment_cancelled,
    record_visit_status_transition,
    record_appointment_booking_time,
)
from app.models import AppointmentStatus, BillingStatus, User, UserRole, VisitStatus
from app.repositories import AppointmentRepository, PatientRepository, SlotRepository
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead
from app.services.base import BaseService
from app.services.healthcare_event_service import HealthcareEventService
from app.workflows.appointment_saga import run_appointment_saga


class AppointmentService(BaseService):
    """Appointment management service with structured logging and event publishing."""
    
    def __init__(self, db):
        super().__init__(db)
        self.appointments = AppointmentRepository(db)
        self.patients = PatientRepository(db)
        self.slots = SlotRepository(db)
        self.events = HealthcareEventService()

    async def create(self, payload: AppointmentCreate, current_user: User, idempotency_key: Optional[str] = None):
        """Create a new appointment with saga workflow."""
        self.log_info("Appointment creation request", operation="create_appointment", data={"user_id": current_user.id})
        booking_start_time = time.time()
        
        if current_user.role != UserRole.patient:
            self.log_warning("Appointment creation denied: invalid role", operation="create_appointment", data={"role": current_user.role})
            raise AppError("Forbidden", status_code=403, error_type="forbidden")

        if idempotency_key:
            cached = idempotency_store.get(current_user.id, idempotency_key)
            if cached:
                self.log_info("Idempotent appointment retrieval", operation="create_appointment", data={"appointment_id": cached["appointment_id"]})
                appointment = self.appointments.get_by_id(cached["appointment_id"])
                if appointment:
                    return appointment

        patient = self.patients.get_by_user_id(current_user.id)
        if not patient:
            self.log_error("Patient profile not found", operation="create_appointment", data={"user_id": current_user.id})
            raise AppError("Patient profile not found", status_code=404, error_type="not_found")

        slot = self.slots.get_by_id(payload.slot_id)
        if not slot:
            self.log_warning("Slot not found", operation="create_appointment", data={"slot_id": payload.slot_id})
            raise AppError("Slot not found", status_code=404, error_type="not_found")
        if slot.status.value != "AVAILABLE":
            self.log_warning("Slot not available", operation="create_appointment", data={"slot_id": slot.id, "status": slot.status.value})
            raise AppError("Slot is no longer available", status_code=409, error_type="conflict")

        self.log_info("Starting appointment saga workflow", operation="create_appointment", data={"patient_id": patient.id, "slot_id": slot.id})
        
        workflow_payload = {
            "patient_id": patient.id,
            "slot_id": slot.id,
            **payload.model_dump(),
        }
        try:
            workflow_result = await run_appointment_saga(workflow_payload)
        except AppError:
            self.log_error("Appointment saga failed: AppError", operation="create_appointment", exc_info=True)
            raise
        except Exception as exc:
            self.log_error("Appointment saga failed", operation="create_appointment", data={"error": str(exc)}, exc_info=True)
            raise AppError("Failed to create appointment", status_code=500, error_type="internal_error", detail=str(exc)) from exc

        appointment = self.appointments.get_by_id(workflow_result["appointment_id"])
        if not appointment:
            self.log_error("Appointment not found after saga", operation="create_appointment", data={"workflow_result": workflow_result})
            raise AppError("Appointment not found after saga execution", status_code=404, error_type="not_found")

        if idempotency_key:
            idempotency_store.set(current_user.id, idempotency_key, {"appointment_id": appointment.id})

        self.log_info("Appointment created successfully", operation="create_appointment", data={"appointment_id": appointment.id})
        
        # Record metrics
        try:
            record_appointment_created()
            booking_duration = time.time() - booking_start_time
            record_appointment_booking_time(booking_duration)
        except Exception as exc:
            self.log_error("Failed to record appointment creation metrics", operation="create_appointment", data={"error": str(exc)})
        
        self.events.publish_appointment_event(
            "appointment.created",
            appointment_id=appointment.id,
            patient_id=patient.id,
            provider_id=appointment.provider_id,
            service_id=appointment.service_id,
            slot_id=appointment.slot_id,
            status=appointment.status.value,
        )

        return appointment

    def get_state(self, appointment_id: int, current_user: User) -> dict[str, str]:
        """Get appointment state with authorization."""
        self.log_info("Retrieving appointment state", operation="get_appointment_state", data={"appointment_id": appointment_id, "user_id": current_user.id})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            self.log_warning("Appointment not found", operation="get_appointment_state", data={"appointment_id": appointment_id})
            raise AppError("Appointment not found", status_code=404, error_type="not_found")

        if current_user.role == UserRole.patient:
            patient = self.patients.get_by_user_id(current_user.id)
            if not patient or appointment.patient_id != patient.id:
                self.log_warning("Unauthorized access to appointment", operation="get_appointment_state", data={"appointment_id": appointment_id})
                raise AppError("Forbidden", status_code=403, error_type="forbidden")
        elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            self.log_warning("Insufficient role for appointment access", operation="get_appointment_state", data={"role": current_user.role})
            raise AppError("Forbidden", status_code=403, error_type="forbidden")

        return {"id": appointment.id, "status": appointment.status.value, "slot_id": appointment.slot_id}

    def cancel(self, appointment_id: int, current_user: User):
        """Cancel an appointment."""
        self.log_info("Appointment cancellation request", operation="cancel_appointment", data={"appointment_id": appointment_id, "user_id": current_user.id})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            self.log_warning("Appointment not found for cancellation", operation="cancel_appointment", data={"appointment_id": appointment_id})
            raise AppError("Appointment not found", status_code=404, error_type="not_found")

        if current_user.role == UserRole.patient:
            patient = self.patients.get_by_user_id(current_user.id)
            if not patient or appointment.patient_id != patient.id:
                self.log_warning("Unauthorized cancellation attempt", operation="cancel_appointment", data={"appointment_id": appointment_id})
                raise AppError("Forbidden", status_code=403, error_type="forbidden")
        elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")

        if appointment.status.value in {AppointmentStatus.CANCELLED.value, AppointmentStatus.COMPLETED.value}:
            self.log_warning("Cannot cancel terminal appointment", operation="cancel_appointment", data={"appointment_id": appointment_id, "status": appointment.status.value})
            raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

        self.log_info("Appointment cancelled", operation="cancel_appointment", data={"appointment_id": appointment_id})
        
        # Record metrics
        try:
            record_appointment_cancelled()
        except Exception as exc:
            self.log_error("Failed to record cancellation metric", operation="cancel_appointment", data={"error": str(exc)})
        
        return self.appointments.cancel(appointment)

    def reschedule(self, appointment_id: int, slot_id: int, current_user: User):
        """Reschedule an appointment to a new slot."""
        self.log_info("Appointment reschedule request", operation="reschedule_appointment", data={"appointment_id": appointment_id, "slot_id": slot_id})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")

        if current_user.role == UserRole.patient:
            patient = self.patients.get_by_user_id(current_user.id)
            if not patient or appointment.patient_id != patient.id:
                raise AppError("Forbidden", status_code=403, error_type="forbidden")
        elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")

        if appointment.status.value in {AppointmentStatus.CANCELLED.value, AppointmentStatus.COMPLETED.value}:
            self.log_warning("Cannot reschedule terminal appointment", operation="reschedule_appointment", data={"appointment_id": appointment_id})
            raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

        new_slot = self.slots.get_by_id(slot_id)
        if not new_slot:
            raise AppError("Replacement slot not found", status_code=404, error_type="not_found")
        if new_slot.status.value != "AVAILABLE":
            raise AppError("Replacement slot is no longer available", status_code=409, error_type="conflict")

        self.log_info("Appointment rescheduled", operation="reschedule_appointment", data={"appointment_id": appointment_id, "old_slot": appointment.slot_id, "new_slot": new_slot.id})
        return self.appointments.reschedule(appointment, new_slot)

    def transition_visit_status(self, appointment_id: int, target_status: VisitStatus, current_user: User):
        """Transition appointment visit status."""
        self.log_info("Visit status transition request", operation="transition_visit_status", data={"appointment_id": appointment_id, "target_status": target_status.value})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")
        if current_user.role == UserRole.patient:
            patient = self.patients.get_by_user_id(current_user.id)
            if not patient or appointment.patient_id != patient.id:
                raise AppError("Forbidden", status_code=403, error_type="forbidden")
        elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")

        if appointment.visit_status == target_status:
            self.log_info("Visit already in target status", operation="transition_visit_status", data={"appointment_id": appointment_id})
            return {"appointment_id": appointment.id, "visit_status": appointment.visit_status.value}

        if target_status == VisitStatus.CHECKED_IN:
            if appointment.visit_status not in {VisitStatus.NOT_STARTED, VisitStatus.CHECKED_IN}:
                raise AppError("Visit is already in a later state", status_code=409, error_type="conflict")
        elif target_status == VisitStatus.IN_PROGRESS:
            if appointment.visit_status not in {VisitStatus.CHECKED_IN, VisitStatus.IN_PROGRESS}:
                raise AppError("Visit must be checked in before starting", status_code=409, error_type="conflict")
        elif target_status == VisitStatus.COMPLETED:
            if appointment.visit_status != VisitStatus.IN_PROGRESS:
                raise AppError("Visit must be in progress before completion", status_code=409, error_type="conflict")

        updated = self.appointments.transition_visit_status(appointment, target_status)
        
        self.log_info("Visit status transitioned", operation="transition_visit_status", data={"appointment_id": updated.id, "visit_status": updated.visit_status.value})
        
        # Record metrics
        try:
            record_visit_status_transition(from_status=appointment.visit_status.value, to_status=target_status.value)
        except Exception as exc:
            self.log_error("Failed to record visit status transition metric", operation="transition_visit_status", data={"error": str(exc)})
        
        self.events.publish_appointment_event(
            "appointment.visit_status_changed",
            appointment_id=updated.id,
            patient_id=appointment.patient_id,
            provider_id=appointment.provider_id,
            service_id=appointment.service_id,
            slot_id=updated.slot_id,
            status=updated.status.value,
            visit_status=updated.visit_status.value,
        )
        return {"appointment_id": updated.id, "visit_status": updated.visit_status.value}

    def billing_pre_check(self, appointment_id: int, current_user: User):
        """Perform billing precheck for appointment."""
        self.log_info("Billing precheck requested", operation="billing_precheck", data={"appointment_id": appointment_id})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")

        if current_user.role == UserRole.patient:
            patient = self.patients.get_by_user_id(current_user.id)
            if not patient or appointment.patient_id != patient.id:
                raise AppError("Forbidden", status_code=403, error_type="forbidden")
        elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")

        existing = self.appointments.get_billing_by_appointment_id(appointment.id)
        if existing:
            self.log_info("Existing billing found", operation="billing_precheck", data={"appointment_id": appointment_id, "status": existing.status.value})
            return existing
        
        self.log_info("Creating new billing record", operation="billing_precheck", data={"appointment_id": appointment_id})
        return self.appointments.create_billing(appointment.id)