from typing import Optional
import time

from sqlalchemy.exc import IntegrityError
from app.core.exceptions import AppError, app_error, conflict_error, forbidden_error, not_found_error, ForbiddenError
from app.core.authorization import authorize, Permission
from app.core.idempotency import idempotency_store
from app.core.settings import settings
from app.core.metrics import (
    record_appointment_created,
    record_appointment_cancelled,
    record_visit_status_transition,
    record_appointment_booking_time,
)
from app.models import AppointmentStatus, BillingStatus, User, UserRole, VisitStatus, SlotStatus, WaitlistEntry, WaitlistStatus
from app.repositories import AppointmentRepository, PatientRepository, ProviderRepository, SlotRepository, WaitlistRepository
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead
from app.services.base import BaseService
from app.services.healthcare_event_service import HealthcareEventService
from app.workers.temporal.workflows.appointment_saga import run_appointment_saga, start_appointment_saga


class AppointmentService(BaseService):
    """Appointment management service with structured logging and event publishing."""
    
    def __init__(self, db):
        super().__init__(db)
        self.appointments = AppointmentRepository(db)
        self.patients = PatientRepository(db)
        self.providers = ProviderRepository(db)
        self.slots = SlotRepository(db)
        self.events = HealthcareEventService(db)

    def _authorize(self, appointment, current_user: User) -> None:
        authorize(
            current_user,
            Permission.APPOINTMENT_READ,
            appointment,
            patient_repository=self.patients,
            provider_repository=self.providers,
        )

    def join_waitlist(self, slot_id: int, current_user: User) -> WaitlistEntry:
        """Join waitlist for a slot."""
        self.log_info("Waitlist join request", operation="join_waitlist", data={"slot_id": slot_id, "user_id": current_user.id})
        patient = self.patients.get_by_user_id(current_user.id)
        slot = self.slots.get_by_id(slot_id)
        if not patient or not slot:
            self.log_warning("Patient or slot not found for waitlist", operation="join_waitlist", data={"slot_id": slot_id})
            raise not_found_error("Slot or patient not found")
        if slot.status == SlotStatus.AVAILABLE:
            self.log_warning("Cannot join waitlist: slot is available", operation="join_waitlist", data={"slot_id": slot_id})
            raise conflict_error("Slot is still available")
        return WaitlistRepository(self.db).join(slot_id, patient.id)

    async def create(
        self,
        payload: AppointmentCreate,
        current_user: User,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        """Create a new appointment with saga workflow."""
        self.log_info("Appointment creation request", operation="create_appointment", data={"user_id": current_user.id})
        booking_start_time = time.time()
        
        try:
            authorize(current_user, Permission.APPOINTMENT_CREATE)
        except ForbiddenError as exc:
            self.log_warning("Appointment creation denied: invalid role", operation="create_appointment", data={"role": current_user.role})
            raise exc

        if idempotency_key:
            cached = idempotency_store.get(current_user.id, idempotency_key)
            if cached:
                if cached.get("status") == "IN_PROGRESS":
                    raise AppError("A booking with this idempotency key is in progress", status_code=409, error_type="idempotency_in_progress")
                self.log_info("Idempotent appointment retrieval", operation="create_appointment", data={"appointment_id": cached["appointment_id"]})
                appointment = self.appointments.get_by_id(cached["appointment_id"])
                if appointment and appointment.status != AppointmentStatus.CANCELLED:
                    return appointment
                idempotency_store.delete(current_user.id, idempotency_key)

        patient = self.patients.get_by_user_id(current_user.id)
        if not patient:
            self.log_error("Patient profile not found", operation="create_appointment", data={"user_id": current_user.id})
            raise not_found_error("Patient profile not found")

        slot = self.slots.get_by_id(payload.slot_id)
        if not slot:
            self.log_warning("Slot not found", operation="create_appointment", data={"slot_id": payload.slot_id})
            raise not_found_error("Slot not found")
        if slot.status != SlotStatus.AVAILABLE:
            self.log_warning("Slot not available", operation="create_appointment", data={"slot_id": slot.id, "status": slot.status})
            raise conflict_error("Slot is no longer available")

        if idempotency_key and not idempotency_store.claim(current_user.id, idempotency_key):
            raise AppError("A booking with this idempotency key is in progress", status_code=409, error_type="idempotency_in_progress")

        workflow_payload = {
            **payload.model_dump(),
            "patient_id": patient.id,
            "slot_id": slot.id,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
        }

        if settings.async_booking_enabled:
            try:
                appointment = self.appointments.create_pending(
                    patient_id=patient.id,
                    provider_id=slot.provider_id,
                    service_id=slot.service_id,
                    slot_id=slot.id,
                    booking_key=idempotency_key,
                )
                workflow_payload["appointment_id"] = appointment.id
                await start_appointment_saga(workflow_payload)
            except Exception as exc:
                self.log_error("Failed to start appointment saga workflow", operation="create_appointment", exc_info=True)
                self.appointments.rollback()
                if idempotency_key:
                    idempotency_store.delete(current_user.id, idempotency_key)
                raise AppError("Failed to start appointment workflow", status_code=503, error_type="workflow_unavailable") from exc
            
            if idempotency_key:
                idempotency_store.set(current_user.id, idempotency_key, {"appointment_id": appointment.id})
            return appointment

        self.log_info("Starting appointment saga workflow", operation="create_appointment", data={"patient_id": patient.id, "slot_id": slot.id})
        try:
            workflow_result = await run_appointment_saga(workflow_payload)
        except AppError:
            self.log_error("Appointment saga failed: AppError", operation="create_appointment", exc_info=True)
            if idempotency_key:
                idempotency_store.delete(current_user.id, idempotency_key)
            raise
        except Exception as exc:
            self.log_error("Appointment saga failed", operation="create_appointment", data={"error": str(exc)}, exc_info=True)
            if idempotency_key:
                idempotency_store.delete(current_user.id, idempotency_key)
            raise AppError("Failed to create appointment", status_code=500, error_type="internal_error") from exc

        appointment = self.appointments.get_by_id(workflow_result["appointment_id"])
        if not appointment:
            self.log_error("Appointment not found after saga", operation="create_appointment", data={"workflow_result": workflow_result})
            raise not_found_error("Appointment not found after saga execution")

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
            raise not_found_error("Appointment not found")

        self._authorize(appointment, current_user)

        return {
            "id": appointment.id,
            "status": appointment.status.value,
            "visit_status": appointment.visit_status.value,
            "slot_id": appointment.slot_id,
        }

    def list(self, limit: int, offset: int, current_user: User):
        patient_id = None
        provider_id = None
        if current_user.role == UserRole.patient:
            patient = self.patients.get_by_user_id(current_user.id)
            if not patient:
                raise not_found_error("Patient profile not found")
            patient_id = patient.id
        elif current_user.role == UserRole.provider:
            provider = self.providers.get_by_user_id(current_user.id)
            if not provider:
                raise not_found_error("Provider profile not found")
            provider_id = provider.id
        elif current_user.role not in {UserRole.admin, UserRole.front_desk}:
            raise forbidden_error()
        items, total = self.appointments.list_scoped(patient_id=patient_id, provider_id=provider_id, limit=limit, offset=offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def cancel(self, appointment_id: int, current_user: User):
        """Cancel an appointment."""
        self.log_info("Appointment cancellation request", operation="cancel_appointment", data={"appointment_id": appointment_id, "user_id": current_user.id})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            self.log_warning("Appointment not found for cancellation", operation="cancel_appointment", data={"appointment_id": appointment_id})
            raise not_found_error("Appointment not found")

        self._authorize(appointment, current_user)

        if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
            self.log_warning("Cannot cancel terminal appointment", operation="cancel_appointment", data={"appointment_id": appointment_id, "status": appointment.status.value})
            raise conflict_error("Appointment is already in a terminal state")

        self.log_info("Appointment cancelled", operation="cancel_appointment", data={"appointment_id": appointment_id})
        
        # Record metrics
        try:
            record_appointment_cancelled()
        except Exception as exc:
            self.log_error("Failed to record cancellation metric", operation="cancel_appointment", data={"error": str(exc)})
        
        cancelled = self.appointments.cancel(appointment)
        
        self.events.publish_appointment_event(
            "appointment.cancelled",
            appointment_id=cancelled.id,
            patient_id=cancelled.patient_id,
            provider_id=cancelled.provider_id,
            service_id=cancelled.service_id,
            slot_id=cancelled.slot_id,
            status=cancelled.status.value,
        )
        return cancelled

    def reschedule(self, appointment_id: int, slot_id: int, current_user: User):
        """Reschedule an appointment to a new slot."""
        self.log_info("Appointment reschedule request", operation="reschedule_appointment", data={"appointment_id": appointment_id, "slot_id": slot_id})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            raise not_found_error("Appointment not found")

        self._authorize(appointment, current_user)

        if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
            self.log_warning("Cannot reschedule terminal appointment", operation="reschedule_appointment", data={"appointment_id": appointment_id})
            raise conflict_error("Appointment is already in a terminal state")

        new_slot = self.slots.get_by_id(slot_id)
        if not new_slot:
            raise not_found_error("Replacement slot not found")
        if new_slot.status != SlotStatus.AVAILABLE:
            raise conflict_error("Replacement slot is no longer available")
        if new_slot.provider_id != appointment.provider_id or new_slot.service_id != appointment.service_id:
            raise conflict_error("Replacement slot must use the same provider and service")

        old_slot_id = appointment.slot_id
        try:
            updated = self.appointments.reschedule(appointment, new_slot)
        except ValueError as exc:
            raise conflict_error(str(exc)) from exc

        self.log_info("Appointment rescheduled", operation="reschedule_appointment", data={"appointment_id": appointment_id, "old_slot": appointment.slot_id, "new_slot": new_slot.id})
        
        self.events.publish_appointment_event(
            "appointment.rescheduled",
            appointment_id=updated.id,
            patient_id=updated.patient_id,
            provider_id=updated.provider_id,
            service_id=updated.service_id,
            slot_id=updated.slot_id,
            old_slot_id=old_slot_id,
            new_slot_id=updated.slot_id,
            status=updated.status.value,
        )
        return updated

    def transition_visit_status(self, appointment_id: int, target_status: VisitStatus, current_user: User):
        """Transition appointment visit status."""
        self.log_info("Visit status transition request", operation="transition_visit_status", data={"appointment_id": appointment_id, "target_status": target_status.value})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            raise not_found_error("Appointment not found")

        authorize(
            current_user,
            Permission.VISIT_UPDATE,
            appointment,
            target_status=target_status,
            provider_repository=self.providers,
        )

        if appointment.status != AppointmentStatus.CONFIRMED:
            raise AppError(
                f"Appointment {appointment.id} has status {appointment.status.value}; only CONFIRMED appointments can enter the visit workflow",
                status_code=409,
                error_type="conflict",
            )

        if appointment.visit_status == target_status:
            self.log_info("Visit already in target status", operation="transition_visit_status", data={"appointment_id": appointment_id})
            return {"appointment_id": appointment.id, "visit_status": appointment.visit_status.value}

        if target_status == VisitStatus.CHECKED_IN:
            if appointment.visit_status not in {VisitStatus.NOT_STARTED, VisitStatus.CHECKED_IN}:
                raise conflict_error("Visit is already in a later state")
        elif target_status == VisitStatus.IN_PROGRESS:
            if appointment.visit_status not in {VisitStatus.CHECKED_IN, VisitStatus.IN_PROGRESS}:
                raise conflict_error("Visit must be checked in before starting")
        elif target_status == VisitStatus.COMPLETED:
            if appointment.visit_status != VisitStatus.IN_PROGRESS:
                raise conflict_error("Visit must be in progress before completion")

        try:
            updated = self.appointments.transition_visit_status(
                appointment,
                target_status,
                actor=f"user:{current_user.id}",
                reason=f"visit transition to {target_status.value}",
            )
        except ValueError as exc:
            raise conflict_error(str(exc)) from exc
        
        self.log_info("Visit status transitioned", operation="transition_visit_status", data={"appointment_id": updated.id, "visit_status": updated.visit_status.value})
        
        # Record metrics
        try:
            record_visit_status_transition(from_status=appointment.visit_status.value, to_status=target_status.value)
        except Exception as exc:
            self.log_error("Failed to record visit status transition metric", operation="transition_visit_status", data={"error": str(exc)})
        
        # If COMPLETED, run post-completion side-effects
        if target_status == VisitStatus.COMPLETED:
            from app.services.billing_checker import BillingChecker
            from app.services.notification_service import NotificationService
            try:
                BillingChecker(self.db).precheck(appointment, idempotency_key=f"completion:{appointment.id}")
            except Exception:
                self.log_error("Completion billing update failed", operation="transition_visit_status", data={"appointment_id": appointment.id}, exc_info=True)
            try:
                NotificationService(self.db).create_follow_up(appointment)
                from app.core.settings import settings
                if not settings.celery_task_always_eager:
                    from app.workers.celery.appointments import send_visit_follow_up
                    send_visit_follow_up.delay(appointment.id)
            except Exception:
                self.log_error("Completion follow-up notification failed", operation="transition_visit_status", data={"appointment_id": appointment.id}, exc_info=True)
            try:
                checked_in_at = appointment.visit.checked_in_at if appointment.visit else None
                scheduled_at = appointment.slot.start_datetime if appointment.slot else None
                wait_seconds = int((checked_in_at - scheduled_at).total_seconds()) if checked_in_at and scheduled_at else None
                self.events.publish_appointment_event(
                    "visit.completed",
                    appointment_id=appointment.id,
                    patient_id=appointment.patient_id,
                    provider_id=appointment.provider_id,
                    service_id=appointment.service_id,
                    slot_id=appointment.slot_id,
                    status=appointment.status.value,
                    visit_status=VisitStatus.COMPLETED.value,
                    scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
                    checked_in_at=checked_in_at.isoformat() if checked_in_at else None,
                    wait_seconds=wait_seconds,
                )
            except Exception:
                self.log_error("Completion analytics event failed", operation="transition_visit_status", data={"appointment_id": appointment.id}, exc_info=True)
        else:
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

    def mark_no_show(self, appointment_id: int, current_user: User):
        """Mark appointment as no-show."""
        self.log_info("Mark no-show request", operation="mark_no_show", data={"appointment_id": appointment_id, "user_id": current_user.id})
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            raise not_found_error("Appointment not found")
        
        authorize(
            current_user,
            Permission.APPOINTMENT_UPDATE,
            appointment,
            is_no_show=True,
            provider_repository=self.providers,
        )
        
        if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}:
            raise conflict_error("Appointment is already in a terminal state")
        
        return self.appointments.mark_no_show(appointment)

    def billing_pre_check(self, appointment_id: int, current_user: User):
        """Perform billing precheck for appointment."""
        self.log_info("Billing precheck requested", operation="billing_precheck", data={"appointment_id": appointment_id})
        
        appointment = self.appointments.get_by_id(appointment_id)
        if not appointment:
            raise not_found_error("Appointment not found")

        authorize(
            current_user,
            Permission.BILLING_CREATE,
            appointment,
            patient_repository=self.patients,
            provider_repository=self.providers,
        )

        existing = self.appointments.get_billing_by_appointment_id(appointment.id)
        if existing:
            self.log_info("Existing billing found", operation="billing_precheck", data={"appointment_id": appointment_id, "status": existing.status.value})
            return existing
        
        self.log_info("Creating new billing record", operation="billing_precheck", data={"appointment_id": appointment_id})
        from app.services.billing_checker import BillingChecker
        try:
            billing = BillingChecker(self.db).precheck(appointment, idempotency_key=f"appointment:{appointment.id}")
        except IntegrityError:
            self.appointments.rollback()
            billing = self.appointments.get_billing_by_appointment_id(appointment.id)
            if billing is None:
                raise AppError("Billing pre-check could not be completed", status_code=503, error_type="billing_unavailable")
        
        self.events.publish_billing_event(
            "billing.precheck.created",
            billing_id=billing.id,
            appointment_id=appointment.id,
            amount=float(billing.amount),
            status=billing.status.value,
        )
        return billing

