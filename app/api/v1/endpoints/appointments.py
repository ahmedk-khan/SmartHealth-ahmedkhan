import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.core.idempotency import idempotency_store
from app.models import Appointment, AppointmentStatus, Provider, SlotStatus, User, UserRole, VisitStatus, WaitlistEntry, WaitlistStatus
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead, PaginatedResponse, WaitlistEntryRead
from app.repositories import AppointmentRepository, PatientRepository, SlotRepository
from app.workflows.appointment_saga import run_appointment_saga
from app.services.healthcare_event_service import HealthcareEventService

router = APIRouter(prefix="/appointments", tags=["appointments"])
logger = logging.getLogger(__name__)


def _ensure_provider_owns_appointment(appointment: Appointment, current_user: User, db: Session) -> None:
    if current_user.role != UserRole.provider:
        return
    provider = db.query(Provider).filter(Provider.user_id == current_user.id).first()
    if not provider or appointment.provider_id != provider.id:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")


def _ensure_visit_role(appointment: Appointment, current_user: User, db: Session, *, provider_only: bool = False) -> None:
    if current_user.role == UserRole.provider:
        _ensure_provider_owns_appointment(appointment, current_user, db)
        return
    allowed_roles = {UserRole.admin, UserRole.provider} if provider_only else {UserRole.admin, UserRole.front_desk, UserRole.provider}
    if current_user.role not in allowed_roles:
        raise AppError("Only authorized staff can update visit status", status_code=403, error_type="forbidden")


@router.post("/waitlist/{slot_id}", response_model=WaitlistEntryRead, status_code=status.HTTP_201_CREATED)
def join_waitlist(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.patient:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    patient = PatientRepository(db).get_by_user_id(current_user.id)
    slot = SlotRepository(db).get_by_id(slot_id)
    if not patient or not slot:
        raise AppError("Slot or patient not found", status_code=404, error_type="not_found")
    if slot.status == SlotStatus.AVAILABLE:
        raise AppError("Slot is still available", status_code=409, error_type="conflict")
    existing = db.query(WaitlistEntry).filter(
        WaitlistEntry.slot_id == slot_id,
        WaitlistEntry.patient_id == patient.id,
    ).order_by(WaitlistEntry.created_at.desc(), WaitlistEntry.id.desc()).first()
    if existing:
        return existing
    entry = WaitlistEntry(slot_id=slot_id, patient_id=patient.id, status=WaitlistStatus.WAITING)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    correlation_id: Optional[str] = Header(
        default="demo-trace-001",
        alias="X-Correlation-ID",
    ),
):
    if current_user.role != UserRole.patient:
        raise AppError(
            "Forbidden",
            status_code=403,
            error_type="forbidden",
        )

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
                raise AppError(
                    "A booking with this idempotency key is in progress",
                    status_code=409,
                    error_type="idempotency_in_progress",
                )

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
        raise AppError(
            "Patient profile not found",
            status_code=404,
            error_type="not_found",
        )

    slot = slot_repository.get_by_id(payload.slot_id)

    if not slot:
        raise AppError(
            "Slot not found",
            status_code=404,
            error_type="not_found",
        )

    if slot.status != SlotStatus.AVAILABLE:
        raise AppError(
            "Slot is no longer available",
            status_code=409,
            error_type="conflict",
        )

    if idempotency_key and not idempotency_store.claim(
        current_user.id,
        idempotency_key,
    ):
        raise AppError(
            "A booking with this idempotency key is in progress",
            status_code=409,
            error_type="idempotency_in_progress",
        )

    payload_data = payload.model_dump()

    workflow_payload = {
        "patient_id": patient.id,
        "slot_id": slot.id,
        "idempotency_key": idempotency_key,
        **payload_data,
    }

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

    HealthcareEventService().publish_appointment_event(
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
    query = db.query(Appointment)
    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient:
            raise AppError("Patient profile not found", status_code=404, error_type="not_found")
        query = query.filter(Appointment.patient_id == patient.id)
    elif current_user.role == UserRole.provider:
        provider = db.query(Provider).filter(Provider.user_id == current_user.id).first()
        if not provider:
            raise AppError("Provider profile not found", status_code=404, error_type="not_found")
        query = query.filter(Appointment.provider_id == provider.id)
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    total = query.count()
    items = query.order_by(Appointment.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{appointment_id}/state", response_model=dict)
def get_appointment_state(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)

    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    return {"id": appointment.id, "status": appointment.status.value, "slot_id": appointment.slot_id}


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)

    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

    cancelled = appointment_repository.cancel(appointment)
    HealthcareEventService().publish_appointment_event(
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

    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

    new_slot = SlotRepository(db).get_by_id(payload.slot_id)
    if not new_slot:
        raise AppError("Replacement slot not found", status_code=404, error_type="not_found")
    if new_slot.status != SlotStatus.AVAILABLE:
        raise AppError("Replacement slot is no longer available", status_code=409, error_type="conflict")

    old_slot_id = appointment.slot_id
    try:
        updated = appointment_repository.reschedule(appointment, new_slot)
    except ValueError as exc:
        raise AppError(str(exc), status_code=409, error_type="conflict") from exc
    HealthcareEventService().publish_appointment_event(
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


def _transition_visit_status(appointment: Appointment, target_status: VisitStatus, db: Session) -> dict[str, str]:
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
        updated = appointment_repository.transition_visit_status(appointment, target_status)
    except ValueError as exc:
        raise AppError(str(exc), status_code=409, error_type="conflict") from exc
    return {"appointment_id": updated.id, "visit_status": updated.visit_status.value}


@router.post("/{appointment_id}/visit/check-in", response_model=dict)
def check_in_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_visit_role(appointment, current_user, db)

    return _transition_visit_status(appointment, VisitStatus.CHECKED_IN, db)


@router.post("/{appointment_id}/visit/start", response_model=dict)
def start_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_visit_role(appointment, current_user, db, provider_only=True)

    return _transition_visit_status(appointment, VisitStatus.IN_PROGRESS, db)


@router.post("/{appointment_id}/visit/complete", response_model=dict)
def complete_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_visit_role(appointment, current_user, db, provider_only=True)

    return _transition_visit_status(appointment, VisitStatus.COMPLETED, db)


@router.post("/{appointment_id}/no-show", response_model=AppointmentRead)
def mark_no_show(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    _ensure_provider_owns_appointment(appointment, current_user, db)
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
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

    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    existing = appointment_repository.get_billing_by_appointment_id(appointment.id)
    if existing:
        return existing

    try:
        billing = appointment_repository.create_billing(appointment.id)
    except IntegrityError:
        db.rollback()
        billing = appointment_repository.get_billing_by_appointment_id(appointment.id)
        if billing is None:
            raise AppError("Billing pre-check could not be completed", status_code=503, error_type="billing_unavailable")
    HealthcareEventService().publish_billing_event(
        "billing.precheck.created",
        billing_id=billing.id,
        appointment_id=appointment.id,
        amount=float(billing.amount),
        status=billing.status.value,
    )
    return billing
