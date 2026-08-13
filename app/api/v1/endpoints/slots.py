import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.models import SlotStatus, User, UserRole
from app.repositories import SlotRepository
from app.schemas.domain import PaginatedResponse, SlotCreate, SlotRead

router = APIRouter(prefix="/slots", tags=["slots"])


@router.post("", response_model=SlotRead, status_code=status.HTTP_200_OK)
def create_slot(payload: SlotCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    repository = SlotRepository(db)
    if not repository.validate_provider_and_service(payload.provider_id, payload.service_id):
        raise AppError("Provider or service not found", status_code=404, error_type="not_found")
    return repository.create_slot(payload.model_dump())


@router.post("/{slot_id}/reserve", response_model=SlotRead, status_code=status.HTTP_200_OK)
def reserve_slot(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.patient:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    repository = SlotRepository(db)
    patient = repository.get_patient_by_user_id(current_user.id)
    if not patient:
        raise AppError("Patient profile not found", status_code=404, error_type="not_found")

    slot = repository.reserve_for_patient(slot_id, patient.id)
    if not slot:
        raise AppError("Slot is no longer available", status_code=409, error_type="conflict")
    return slot


@router.get("", response_model=PaginatedResponse[SlotRead])
def list_slots(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    repository = SlotRepository(db)
    items, total = repository.list_slots(offset=offset, limit=limit, patient_only_available=current_user.role == UserRole.patient)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
