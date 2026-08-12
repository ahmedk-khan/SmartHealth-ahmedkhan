import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.models import Patient, Provider, Service, Slot, SlotStatus, User, UserRole
from app.schemas.domain import PaginatedResponse, SlotCreate, SlotRead

router = APIRouter(prefix="/slots", tags=["slots"])


@router.post("", response_model=SlotRead, status_code=status.HTTP_200_OK)
def create_slot(payload: SlotCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    provider = db.query(Provider).filter(Provider.id == payload.provider_id).first()
    service = db.query(Service).filter(Service.id == payload.service_id).first()
    if not provider or not service:
        raise AppError("Provider or service not found", status_code=404, error_type="not_found")
    slot = Slot(**payload.model_dump())
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


@router.post("/{slot_id}/reserve", response_model=SlotRead, status_code=status.HTTP_200_OK)
def reserve_slot(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.patient:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        raise AppError("Patient profile not found", status_code=404, error_type="not_found")

    now = datetime.datetime.now(datetime.timezone.utc)
    updated = db.query(Slot).filter(Slot.id == slot_id, Slot.status == SlotStatus.AVAILABLE).update(
        {"status": SlotStatus.RESERVED, "patient_id": patient.id, "updated_at": now}, synchronize_session=False
    )
    if updated != 1:
        raise AppError("Slot is no longer available", status_code=409, error_type="conflict")
    db.commit()
    slot = db.query(Slot).filter(Slot.id == slot_id).first()
    return slot


@router.get("", response_model=PaginatedResponse[SlotRead])
def list_slots(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Slot)
    if current_user.role == UserRole.patient:
        query = query.filter(Slot.status == SlotStatus.AVAILABLE)
    total = query.count()
    items = query.order_by(Slot.start_datetime).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}
