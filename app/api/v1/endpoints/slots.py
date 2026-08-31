from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.authorization import require_permission, authorize, Permission
from app.core.exceptions import (
    NotFoundError,
    PatientNotFoundError,
    SlotNotFoundError,
    ConflictError,
    ValidationError,
)
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
def create_slot(payload: SlotCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SLOT_CREATE))):
    repository = SlotRepository(db)
    authorize(
        current_user,
        Permission.SLOT_CREATE,
        payload.provider_id,
        provider_repository=ProviderRepository(db),
    )
    if not repository.validate_provider_and_service(payload.provider_id, payload.service_id):
        raise NotFoundError("Provider or service not found", code="PROVIDER_OR_SERVICE_NOT_FOUND")
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
def reserve_slot(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SLOT_RESERVE))):
    repository = SlotRepository(db)
    patient = repository.get_patient_by_user_id(current_user.id)
    if not patient:
        raise PatientNotFoundError("Patient profile not found")

    slot = repository.reserve_for_patient(slot_id, patient.id)
    if not slot:
        raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE")
    return slot


@router.get(
    "",
    response_model=PaginatedResponse[SlotRead],
    summary="List slots",
    description="Returns a paginated list of slots, filtered for patient availability when applicable.",
)
def list_slots(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SLOT_READ))):
    repository = SlotRepository(db)
    items, total = repository.list_slots(offset=offset, limit=limit, patient_only_available=current_user.role == UserRole.patient)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/{slot_id}", response_model=SlotRead, summary="Update availability slot")
def update_slot(slot_id: int, payload: SlotCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SLOT_UPDATE))):
    slot = SlotRepository(db).get_by_id(slot_id)
    if not slot:
        raise SlotNotFoundError()
    authorize(current_user, Permission.SLOT_UPDATE, slot, provider_repository=ProviderRepository(db))
    if slot.status != SlotStatus.AVAILABLE:
        raise ConflictError("Booked slots cannot be edited", code="SLOT_NOT_EDITABLE")
    if payload.provider_id != slot.provider_id or payload.patient_id is not None or payload.status != SlotStatus.AVAILABLE:
        raise ValidationError("Only an available slot schedule can be edited", code="INVALID_SLOT_UPDATE")
    if payload.end_datetime <= payload.start_datetime:
        raise ValidationError("End time must be after start time", code="INVALID_SLOT_TIME")
    return SlotRepository(db).update_slot(slot, payload.model_dump(exclude={"provider_id", "patient_id", "status"}))


@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete availability slot")
def delete_slot(slot_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.SLOT_DELETE))):
    repository = SlotRepository(db)
    slot = repository.get_by_id(slot_id)
    if not slot:
        raise SlotNotFoundError()
    authorize(current_user, Permission.SLOT_DELETE, slot, provider_repository=ProviderRepository(db))
    if slot.status != SlotStatus.AVAILABLE:
        raise ConflictError("Booked slots cannot be deleted", code="SLOT_NOT_DELETABLE")
    repository.delete_slot(slot)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
