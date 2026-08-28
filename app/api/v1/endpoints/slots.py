from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db, require_patient, require_staff
from app.core.authorization import ensure_provider_ownership, ensure_role
from app.core.exceptions import AppError, forbidden_error
from app.models import SlotStatus, User, UserRole
from app.repositories import ProviderRepository, SlotRepository
from app.schemas.domain import PaginatedResponse, SlotCreate, SlotRead
from app.services.healthcare_event_service import HealthcareEventService

router = APIRouter(prefix="/slots", tags=["slots"])


@router.post(
    "",
    response_model=SlotRead,
    status_code=status.HTTP_200_OK,
    summary="Create slot",
    description="Creates a new availability slot for a provider/service combination. Restricted to admin, front desk, and provider roles.",
)
def create_slot(payload: SlotCreate, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    repository = SlotRepository(db)
    ensure_provider_ownership(
        payload.provider_id,
        current_user,
        ProviderRepository(db),
        "Providers can only publish their own availability",
    )
    if not repository.validate_provider_and_service(payload.provider_id, payload.service_id):
        raise AppError("Provider or service not found", status_code=404, error_type="not_found")
    slot = repository.create_slot(payload.model_dump())
    HealthcareEventService(db).publish_resource_event("slot.created", entity_type="slot", entity_id=slot.id, provider_id=slot.provider_id, service_id=slot.service_id, status=slot.status.value)
    return slot


@router.post(
    "/{slot_id}/reserve",
    response_model=SlotRead,
    status_code=status.HTTP_200_OK,
    summary="Reserve a slot",
    description="Reserves a currently available slot for the authenticated patient.",
)
def reserve_slot(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_patient)):
    repository = SlotRepository(db)
    patient = repository.get_patient_by_user_id(current_user.id)
    if not patient:
        raise AppError("Patient profile not found", status_code=404, error_type="not_found")

    slot = repository.reserve_for_patient(slot_id, patient.id)
    if not slot:
        raise AppError("Slot is no longer available", status_code=409, error_type="conflict")
    return slot


@router.get(
    "",
    response_model=PaginatedResponse[SlotRead],
    summary="List slots",
    description="Returns a paginated list of slots, filtered for patient availability when applicable.",
)
def list_slots(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    repository = SlotRepository(db)
    items, total = repository.list_slots(offset=offset, limit=limit, patient_only_available=current_user.role == UserRole.patient)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _ensure_slot_access(slot, current_user: User, db: Session) -> None:
    if current_user.role != UserRole.provider:
        ensure_role(current_user, {UserRole.admin, UserRole.front_desk})
        return
    ensure_provider_ownership(slot.provider_id, current_user, ProviderRepository(db))


@router.patch("/{slot_id}", response_model=SlotRead, summary="Update availability slot")
def update_slot(slot_id: int, payload: SlotCreate, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    slot = SlotRepository(db).get_by_id(slot_id)
    if not slot:
        raise AppError("Slot not found", status_code=404, error_type="not_found")
    _ensure_slot_access(slot, current_user, db)
    if slot.status != SlotStatus.AVAILABLE:
        raise AppError("Booked slots cannot be edited", status_code=409, error_type="slot_not_editable")
    if payload.provider_id != slot.provider_id or payload.patient_id is not None or payload.status != SlotStatus.AVAILABLE:
        raise AppError("Only an available slot schedule can be edited", status_code=422, error_type="invalid_slot_update")
    if payload.end_datetime <= payload.start_datetime:
        raise AppError("End time must be after start time", status_code=422, error_type="invalid_slot_time")
    return SlotRepository(db).update_slot(slot, payload.model_dump(exclude={"provider_id", "patient_id", "status"}))


@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete availability slot")
def delete_slot(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    repository = SlotRepository(db)
    slot = repository.get_by_id(slot_id)
    if not slot:
        raise AppError("Slot not found", status_code=404, error_type="not_found")
    _ensure_slot_access(slot, current_user, db)
    if slot.status != SlotStatus.AVAILABLE:
        raise AppError("Booked slots cannot be deleted", status_code=409, error_type="slot_not_deletable")
    repository.delete_slot(slot)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
