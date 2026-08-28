import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import get_current_user, get_db, require_patient, require_staff
from app.core.authorization import ensure_appointment_access, ensure_provider_ownership, ensure_role
from app.core.exceptions import AppError
from app.core.idempotency import idempotency_store
from app.core.settings import settings
from app.models import Appointment, AppointmentStatus, SlotStatus, User, UserRole, VisitStatus
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead, PaginatedResponse, WaitlistEntryRead
from app.repositories import AppointmentRepository, PatientRepository, ProviderRepository, SlotRepository, WaitlistRepository
from app.services.appointment_service import AppointmentService
from app.workflows.appointment_saga import run_appointment_saga
from app.services.healthcare_event_service import HealthcareEventService

router = APIRouter(prefix="/appointments", tags=["appointments"])
logger = logging.getLogger(__name__)


def _ensure_provider_owns_appointment(appointment: Appointment, current_user: User, db: Session) -> None:
    ensure_provider_ownership(appointment.provider_id, current_user, ProviderRepository(db))


def _ensure_visit_role(appointment: Appointment, current_user: User, db: Session, *, provider_only: bool = False) -> None:
    if current_user.role == UserRole.provider:
        _ensure_provider_owns_appointment(appointment, current_user, db)
        return
    ensure_role(
        current_user,
        {UserRole.admin, UserRole.provider} if provider_only else {UserRole.admin, UserRole.front_desk, UserRole.provider},
        "Only authorized staff can update visit status",
    )


@router.post("/waitlist/{slot_id}", response_model=WaitlistEntryRead, status_code=status.HTTP_201_CREATED)
def join_waitlist(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_patient)):
    patient = PatientRepository(db).get_by_user_id(current_user.id)
    slot = SlotRepository(db).get_by_id(slot_id)
    if not patient or not slot:
        raise AppError("Slot or patient not found", status_code=404, error_type="not_found")
    if slot.status == SlotStatus.AVAILABLE:
        raise AppError("Slot is still available", status_code=409, error_type="conflict")
    return WaitlistRepository(db).join(slot_id, patient.id)


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_patient),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    correlation_id: Optional[str] = Header(
        default="demo-trace-001",
        alias="X-Correlation-ID",
    ),
):
    appointment_repository = AppointmentRepository(db)
    patient_repository = PatientRepository(db)
    slot_repository = SlotRepository(db)

    if idempotency_key:
        cached = idempotency_store.get(
            current_user.id,
            idempotency_key,
        )

        if cached:
            if cached.get("status") == "IN_PROGRESS":
                raise AppError("A booking with this idempotency key is in progress", status_code=409, error_type="idempotency_in_progress")

            appointment = appointment_repository.get_by_id(
                cached["appointment_id"]
            )

            if appointment and appointment.status != AppointmentStatus.CANCELLED:
                return appointment

            idempotency_store.delete(
                current_user.id,
                idempotency_key,
            )

    patient = patient_repository.get_by_user_id(current_user.id)

    if not patient:
        raise AppError("Patient profile not found", status_code=404, error_type="not_found")

    slot = slot_repository.get_by_id(payload.slot_id)

    if not slot:
        raise AppError("Slot not found", status_code=404, error_type="not_found")

    if slot.status != SlotStatus.AVAILABLE:
        raise AppError("Slot is no longer available", status_code=409, error_type="conflict")

    if idempotency_key and not idempotency_store.claim(
        current_user.id,
        idempotency_key,
    ):
        raise AppError("A booking with this idempotency key is in progress", status_code=409, error_type="idempotency_in_progress")

    payload_data = payload.model_dump()

    workflow_payload = {
        **payload_data,
        "patient_id": patient.id,
        "slot_id": slot.id,
        "idempotency_key": idempotency_key,
        "correlation_id": correlation_id,
    }

    if settings.async_booking_enabled:
        try:
            appointment = appointment_repository.create_pending(
                patient_id=patient.id,
                provider_id=slot.provider_id,
                service_id=slot.service_id,
                slot_id=slot.id,
                booking_key=idempotency_key,
            )
            workflow_payload["appointment_id"] = appointment.id
            from app.workflows.appointment_saga import start_appointment_saga
            await start_appointment_saga(workflow_payload)
        except Exception as exc:
            logger.exception(
                "Failed to start appointment saga workflow",
                extra={
                    "patient_id": patient.id,
                    "slot_id": slot.id,
                    "correlation_id": correlation_id,
                },
            )
            appointment_repository.rollback()
            if idempotency_key:
                idempotency_store.delete(current_user.id, idempotency_key)
            raise AppError("Failed to start appointment workflow", status_code=503, error_type="workflow_unavailable") from exc
        if idempotency_key:
            idempotency_store.set(current_user.id, idempotency_key, {"appointment_id": appointment.id})
        return appointment

    try:
        workflow_result = await run_appointment_saga(workflow_payload)

    except AppError:
        if idempotency_key:
            idempotency_store.delete(
                current_user.id,
                idempotency_key,
            )
        raise

    except Exception as exc:
        if idempotency_key:
            idempotency_store.delete(
                current_user.id,
                idempotency_key,
            )

        logger.exception(
            "Appointment saga failed",
            extra={
                "patient_id": patient.id,
                "slot_id": slot.id,
            },
        )

        raise AppError(
            "Failed to create appointment",
            status_code=500,
            error_type="internal_error",
        ) from exc

    appointment = appointment_repository.get_by_id(
        workflow_result["appointment_id"]
    )

    if not appointment:
        raise AppError(
            "Appointment not found after saga execution",
            status_code=404,
            error_type="not_found",
        )

    appointment = appointment_repository.get_by_id(appointment.id)

    if idempotency_key:
        idempotency_store.set(
            current_user.id,
            idempotency_key,
            {"appointment_id": appointment.id},
        )

    HealthcareEventService(db).publish_appointment_event(
        "appointment.created",
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        provider_id=appointment.provider_id,
        service_id=appointment.service_id,
        slot_id=appointment.slot_id,
        status=appointment.status.value,
    )

    return appointment

@router.get("", response_model=PaginatedResponse[AppointmentRead])
def list_appointments(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return AppointmentService(db).list(limit, offset, current_user)


@router.get("/{appointment_id}/state", response_model=dict)
def get_appointment_state(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)

    ensure_appointment_access(appointment, current_user, PatientRepository(db), ProviderRepository(db))

    return {
        "id": appointment.id,
        "status": appointment.status.value,
        "visit_status": appointment.visit_status.value,
        "slot_id": appointment.slot_id,
    }


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)

    ensure_appointment_access(appointment, current_user, PatientRepository(db), ProviderRepository(db))

    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

    cancelled = appointment_repository.cancel(appointment)
    HealthcareEventService(db).publish_appointment_event(
        "appointment.cancelled",
        appointment_id=cancelled.id,
        patient_id=cancelled.patient_id,
        provider_id=cancelled.provider_id,
        service_id=cancelled.service_id,
        slot_id=cancelled.slot_id,
        status=cancelled.status.value,
    )
    return cancelled


@router.post("/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_appointment(
    appointment_id: int,
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)

    ensure_appointment_access(appointment, current_user, PatientRepository(db), ProviderRepository(db))

    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

    new_slot = SlotRepository(db).get_by_id(payload.slot_id)
    if not new_slot:
        raise AppError("Replacement slot not found", status_code=404, error_type="not_found")
    if new_slot.status != SlotStatus.AVAILABLE:
        raise AppError("Replacement slot is no longer available", status_code=409, error_type="conflict")
    if new_slot.provider_id != appointment.provider_id or new_slot.service_id != appointment.service_id:
        raise AppError("Replacement slot must use the same provider and service", status_code=409, error_type="conflict")

    old_slot_id = appointment.slot_id
    try:
        updated = appointment_repository.reschedule(appointment, new_slot)
    except ValueError as exc:
        raise AppError(str(exc), status_code=409, error_type="conflict") from exc
    HealthcareEventService(db).publish_appointment_event(
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


def _transition_visit_status(appointment: Appointment, target_status: VisitStatus, db: Session, current_user: User) -> dict[str, str]:
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise AppError(
            f"Appointment {appointment.id} has status {appointment.status.value}; only CONFIRMED appointments can enter the visit workflow",
            status_code=409,
            error_type="conflict",
        )
    if appointment.visit_status == target_status:
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

    appointment_repository = AppointmentRepository(db)
    try:
        updated = appointment_repository.transition_visit_status(
            appointment,
            target_status,
            actor=f"user:{current_user.id}",
            reason=f"visit transition to {target_status.value}",
        )
    except ValueError as exc:
        raise AppError(str(exc), status_code=409, error_type="conflict") from exc
    return {"appointment_id": updated.id, "visit_status": updated.visit_status.value}


@router.post("/{appointment_id}/visit/check-in", response_model=dict)
def check_in_visit(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_visit_role(appointment, current_user, db)

    return _transition_visit_status(appointment, VisitStatus.CHECKED_IN, db, current_user)


@router.post("/{appointment_id}/visit/start", response_model=dict)
def start_visit(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_visit_role(appointment, current_user, db, provider_only=True)

    return _transition_visit_status(appointment, VisitStatus.IN_PROGRESS, db, current_user)


@router.post("/{appointment_id}/visit/complete", response_model=dict)
def complete_visit(
    appointment_id: int,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_visit_role(appointment, current_user, db, provider_only=True)

    result = _transition_visit_status(appointment, VisitStatus.COMPLETED, db, current_user)
    from app.services.billing_checker import BillingChecker
    from app.services.notification_service import NotificationService
    try:
        BillingChecker(db).precheck(appointment, idempotency_key=f"completion:{appointment.id}")
    except Exception:
        logger.exception("Completion billing update failed", extra={"appointment_id": appointment.id})
    try:
        NotificationService(db).create_follow_up(appointment)
    except Exception:
        logger.exception("Completion follow-up notification failed", extra={"appointment_id": appointment.id})
    try:
        checked_in_at = appointment.visit.checked_in_at if appointment.visit else None
        scheduled_at = appointment.slot.start_datetime if appointment.slot else None
        wait_seconds = int((checked_in_at - scheduled_at).total_seconds()) if checked_in_at and scheduled_at else None
        HealthcareEventService(db).publish_appointment_event(
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
        logger.exception("Completion analytics event failed", extra={"appointment_id": appointment.id})
    return result


@router.post("/{appointment_id}/no-show", response_model=AppointmentRead)
def mark_no_show(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)
    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")
    return AppointmentRepository(db).mark_no_show(appointment)


@router.post("/{appointment_id}/billing/pre-check", response_model=BillingRead)
def billing_pre_check(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)

    ensure_appointment_access(appointment, current_user, PatientRepository(db), ProviderRepository(db))

    existing = appointment_repository.get_billing_by_appointment_id(appointment.id)
    if existing:
        return existing

    try:
        from app.services.billing_checker import BillingChecker
        billing = BillingChecker(db).precheck(appointment, idempotency_key=f"appointment:{appointment.id}")
    except IntegrityError:
        appointment_repository.rollback()
        billing = appointment_repository.get_billing_by_appointment_id(appointment.id)
        if billing is None:
            raise AppError("Billing pre-check could not be completed", status_code=503, error_type="billing_unavailable")
    HealthcareEventService(db).publish_billing_event(
        "billing.precheck.created",
        billing_id=billing.id,
        appointment_id=appointment.id,
        amount=float(billing.amount),
        status=billing.status.value,
    )
    return billing
