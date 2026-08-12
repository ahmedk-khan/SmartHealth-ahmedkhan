import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.core.idempotency import idempotency_store
from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, BillingStatus, Patient, Slot, SlotStatus, User, UserRole, VisitStatus
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead
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
        raise PermissionError("Forbidden")

    if idempotency_key:
        cached = idempotency_store.get(current_user.id, idempotency_key)
        if cached:
            appointment = db.query(Appointment).filter(Appointment.id == cached["appointment_id"]).first()
            if appointment:
                return appointment

    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        raise ValueError("Patient profile not found")

    slot = db.query(Slot).filter(Slot.id == payload.slot_id).first()
    if not slot:
        raise ValueError("Slot not found")
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
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    appointment = db.query(Appointment).filter(Appointment.id == workflow_result["appointment_id"]).first()
    if not appointment:
        raise ValueError("Appointment not found after saga execution")

    db.refresh(appointment)
    appointment.status = AppointmentStatus.PENDING
    db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))
    db.commit()
    db.refresh(appointment)

    if idempotency_key:
        idempotency_store.set(current_user.id, idempotency_key, {"appointment_id": appointment.id})

    return appointment


@router.get("/{appointment_id}/state", response_model=dict)
def get_appointment_state(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise ValueError("Appointment not found")

    if current_user.role == UserRole.patient:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or appointment.patient_id != patient.id:
            raise PermissionError("Forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")

    return {"id": appointment.id, "status": appointment.status.value, "slot_id": appointment.slot_id}


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise ValueError("Appointment not found")

    if current_user.role == UserRole.patient:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or appointment.patient_id != patient.id:
            raise PermissionError("Forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")

    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

    appointment.status = AppointmentStatus.CANCELLED
    appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))

    slot = db.query(Slot).filter(Slot.id == appointment.slot_id).first()
    if slot:
        slot.status = SlotStatus.AVAILABLE
        slot.patient_id = None
        slot.updated_at = appointment.updated_at

    db.commit()
    db.refresh(appointment)
    return appointment


@router.post("/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_appointment(
    appointment_id: int,
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise ValueError("Appointment not found")

    if current_user.role == UserRole.patient:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or appointment.patient_id != patient.id:
            raise PermissionError("Forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")

    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppError("Appointment is already in a terminal state", status_code=409, error_type="conflict")

    new_slot = db.query(Slot).filter(Slot.id == payload.slot_id).first()
    if not new_slot:
        raise ValueError("Replacement slot not found")
    if new_slot.status != SlotStatus.AVAILABLE:
        raise AppError("Replacement slot is no longer available", status_code=409, error_type="conflict")

    old_slot = db.query(Slot).filter(Slot.id == appointment.slot_id).first()
    if old_slot:
        old_slot.status = SlotStatus.AVAILABLE
        old_slot.patient_id = None
        old_slot.updated_at = datetime.datetime.now(datetime.timezone.utc)

    new_slot.status = SlotStatus.RESERVED
    new_slot.patient_id = appointment.patient_id
    new_slot.updated_at = datetime.datetime.now(datetime.timezone.utc)

    appointment.slot_id = new_slot.id
    appointment.provider_id = new_slot.provider_id
    appointment.service_id = new_slot.service_id
    appointment.status = AppointmentStatus.PENDING
    appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.add(AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status))

    db.commit()
    db.refresh(appointment)
    return appointment


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

    appointment.visit_status = target_status
    appointment.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(appointment)
    return {"appointment_id": appointment.id, "visit_status": appointment.visit_status.value}


@router.post("/{appointment_id}/visit/check-in", response_model=dict)
def check_in_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise ValueError("Appointment not found")
    if current_user.role == UserRole.patient:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or appointment.patient_id != patient.id:
            raise PermissionError("Forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")

    return _transition_visit_status(appointment, VisitStatus.CHECKED_IN, db)


@router.post("/{appointment_id}/visit/start", response_model=dict)
def start_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise ValueError("Appointment not found")
    if current_user.role == UserRole.patient:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or appointment.patient_id != patient.id:
            raise PermissionError("Forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")

    return _transition_visit_status(appointment, VisitStatus.IN_PROGRESS, db)


@router.post("/{appointment_id}/visit/complete", response_model=dict)
def complete_visit(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise ValueError("Appointment not found")
    if current_user.role == UserRole.patient:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or appointment.patient_id != patient.id:
            raise PermissionError("Forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")

    return _transition_visit_status(appointment, VisitStatus.COMPLETED, db)


@router.post("/{appointment_id}/billing/pre-check", response_model=BillingRead)
def billing_pre_check(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise ValueError("Appointment not found")

    if current_user.role == UserRole.patient:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient or appointment.patient_id != patient.id:
            raise PermissionError("Forbidden")
    elif current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise PermissionError("Forbidden")

    existing = db.query(Billing).filter(Billing.appointment_id == appointment.id).first()
    if existing:
        return existing

    billing = Billing(appointment_id=appointment.id, amount=50.0, status=BillingStatus.APPROVED)
    db.add(billing)
    db.commit()
    db.refresh(billing)
    return billing
