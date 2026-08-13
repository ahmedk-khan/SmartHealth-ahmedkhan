import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.core.idempotency import idempotency_store
from app.models import Appointment, AppointmentStatus, BillingStatus, SlotStatus, User, UserRole, VisitStatus
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead
from app.repositories import AppointmentRepository, PatientRepository, SlotRepository
from app.workflows.appointment_saga import run_appointment_saga

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_202_ACCEPTED)
async def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    if current_user.role != UserRole.patient:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    appointment_repository = AppointmentRepository(db)
    patient_repository = PatientRepository(db)
    slot_repository = SlotRepository(db)

    if idempotency_key:
        cached = idempotency_store.get(current_user.id, idempotency_key)
        if cached:
            appointment = appointment_repository.get_by_id(cached["appointment_id"])
            if appointment:
                return appointment

    patient = patient_repository.get_by_user_id(current_user.id)
    if not patient:
        raise AppError("Patient profile not found", status_code=404, error_type="not_found")

    slot = slot_repository.get_by_id(payload.slot_id)
    if not slot:
        raise AppError("Slot not found", status_code=404, error_type="not_found")
    if slot.status != SlotStatus.AVAILABLE:
        raise AppError("Slot is no longer available", status_code=409, error_type="conflict")

    payload_data = payload.model_dump()
    workflow_payload = {
        "patient_id": patient.id,
        "slot_id": slot.id,
        **payload_data,
    }
    try:
        workflow_result = await run_appointment_saga(workflow_payload)
    except AppError:
        raise
    except Exception as exc:
        raise AppError("Failed to create appointment", status_code=500, error_type="internal_error", detail=str(exc)) from exc

    appointment = appointment_repository.get_by_id(workflow_result["appointment_id"])
    if not appointment:
        raise AppError("Appointment not found after saga execution", status_code=404, error_type="not_found")

    appointment = appointment_repository.get_by_id(appointment.id)

    if idempotency_key:
        idempotency_store.set(current_user.id, idempotency_key, {"appointment_id": appointment.id})

    return appointment


@router.get("/{appointment_id}/state", response_model=dict)
def get_appointment_state(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")

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

    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

    return appointment_repository.cancel(appointment)


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

    return appointment_repository.reschedule(appointment, new_slot)


def _transition_visit_status(appointment: Appointment, target_status: VisitStatus, db: Session) -> dict[str, str]:
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
    updated = appointment_repository.transition_visit_status(appointment, target_status)
    return {"appointment_id": updated.id, "visit_status": updated.visit_status.value}


@router.post("/{appointment_id}/visit/check-in", response_model=dict)
def check_in_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    return _transition_visit_status(appointment, VisitStatus.CHECKED_IN, db)


@router.post("/{appointment_id}/visit/start", response_model=dict)
def start_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    return _transition_visit_status(appointment, VisitStatus.IN_PROGRESS, db)


@router.post("/{appointment_id}/visit/complete", response_model=dict)
def complete_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = AppointmentRepository(db).get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")
    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    return _transition_visit_status(appointment, VisitStatus.COMPLETED, db)


@router.post("/{appointment_id}/billing/pre-check", response_model=BillingRead)
def billing_pre_check(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment_repository = AppointmentRepository(db)
    appointment = appointment_repository.get_by_id(appointment_id)
    if not appointment:
        raise AppError("Appointment not found", status_code=404, error_type="not_found")

    if current_user.role == UserRole.patient:
        patient = PatientRepository(db).get_by_user_id(current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise AppError("Forbidden", status_code=403, error_type="forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")

    existing = appointment_repository.get_billing_by_appointment_id(appointment.id)
    if existing:
        return existing

    return appointment_repository.create_billing(appointment.id)
