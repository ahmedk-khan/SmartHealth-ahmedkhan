import datetime
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.models import Appointment, AppointmentStatus, AppointmentStatusHistory, Billing, BillingStatus, Patient, Slot, SlotStatus, User, UserRole
from app.schemas.domain import AppointmentCreate, AppointmentRead, BillingRead

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_202_ACCEPTED)
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.patient:
        raise PermissionError("Forbidden")

    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        raise ValueError("Patient profile not found")

    slot = db.query(Slot).filter(Slot.id == payload.slot_id).first()
    if not slot:
        raise ValueError("Slot not found")
    if slot.status != SlotStatus.AVAILABLE:
        raise AppError("Slot is no longer available", status_code=409, error_type="conflict")

    now = datetime.datetime.now(datetime.timezone.utc)
    slot.status = SlotStatus.RESERVED
    slot.patient_id = patient.id
    slot.updated_at = now

    appointment = Appointment(
        patient_id=patient.id,
        provider_id=slot.provider_id,
        service_id=slot.service_id,
        slot_id=slot.id,
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    db.flush()

    history_entry = AppointmentStatusHistory(appointment_id=appointment.id, status=appointment.status)
    db.add(history_entry)
    db.commit()
    db.refresh(appointment)
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
