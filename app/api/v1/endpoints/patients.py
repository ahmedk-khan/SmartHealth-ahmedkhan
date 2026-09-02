from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.authorization import require_permission, Permission, PatientOwnershipGuard
from app.core.dependencies import get_db
from app.core.exceptions import (
    AppError,
    ForbiddenError,
    ConflictError,
    PatientNotFoundError,
    ProviderNotFoundError,
)
from app.models import User, UserRole
from app.repositories import PatientRepository, ProviderRepository
from app.schemas.domain import PaginatedResponse, PatientRead, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get(
    "",
    response_model=PaginatedResponse[PatientRead],
    summary="List patients",
    description="Returns a paginated, searchable patient directory for administrative, front-desk, or provider care context.",
)
def list_patients(
    search: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.PATIENT_READ)),
):
    if current_user.role == UserRole.provider:
        provider = ProviderRepository(db).get_by_user_id(current_user.id)
        if not provider:
            raise ProviderNotFoundError("Provider profile not found")
        items, total = PatientRepository(db).list_provider_patients(provider.id, offset=offset, limit=limit, search=search)
    elif current_user.role in {UserRole.admin, UserRole.front_desk}:
        items, total = PatientRepository(db).list_patients(offset=offset, limit=limit, search=search)
    else:
        raise ForbiddenError()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{patient_id}",
    response_model=PatientRead,
    summary="Get patient profile",
    description="Fetches a patient profile by patient ID and enforces role-based access control.",
)
def read_patient(patient_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission(Permission.PATIENT_READ))):
    repository = PatientRepository(db)
    patient = repository.get_by_id_or_user_id(patient_id)
    if not patient:
        raise PatientNotFoundError()
    PatientOwnershipGuard(current_user, patient).enforce()
    return patient


@router.patch("/{patient_id}", response_model=PatientRead, summary="Update patient profile")
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.PATIENT_UPDATE)),
):
    repository = PatientRepository(db)
    patient = repository.get_by_id_or_user_id(patient_id)
    if not patient:
        raise PatientNotFoundError()
    PatientOwnershipGuard(current_user, patient).enforce()
    return repository.update_profile(patient, payload.first_name, payload.last_name)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete patient profile")
def delete_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.PATIENT_DELETE)),
):
    repository = PatientRepository(db)
    patient = repository.get_by_id_or_user_id(patient_id)
    if not patient:
        raise PatientNotFoundError()
    PatientOwnershipGuard(current_user, patient).enforce()
    if patient.appointments:
        raise ConflictError(
            "Profiles with appointment history cannot be deleted",
            code="PROFILE_HAS_HISTORY",
        )
    repository.delete_profile(patient)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
