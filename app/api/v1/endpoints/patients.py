from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.models import Provider, User, UserRole
from app.repositories import PatientRepository
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
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.provider:
        provider = db.query(Provider).filter(Provider.user_id == current_user.id).first()
        if not provider:
            raise AppError("Provider profile not found", status_code=404, error_type="not_found")
        items, total = PatientRepository(db).list_provider_patients(provider.id, offset=offset, limit=limit, search=search)
    elif current_user.role in {UserRole.admin, UserRole.front_desk}:
        items, total = PatientRepository(db).list_patients(offset=offset, limit=limit, search=search)
    else:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{patient_id}",
    response_model=PatientRead,
    summary="Get patient profile",
    description="Fetches a patient profile by patient ID and enforces role-based access control.",
)
def read_patient(patient_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    repository = PatientRepository(db)
    patient = repository.get_by_id_or_user_id(patient_id)
    if not patient:
        raise AppError("Patient not found", status_code=404, error_type="not_found")
    if current_user.role not in {UserRole.admin, UserRole.front_desk} and current_user.id != patient.user_id:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    return patient


@router.patch("/{patient_id}", response_model=PatientRead, summary="Update patient profile")
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repository = PatientRepository(db)
    patient = repository.get_by_id_or_user_id(patient_id)
    if not patient:
        raise AppError("Patient not found", status_code=404, error_type="not_found")
    if current_user.role not in {UserRole.admin, UserRole.front_desk} and current_user.id != patient.user_id:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    return repository.update_profile(patient, payload.first_name, payload.last_name)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete patient profile")
def delete_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repository = PatientRepository(db)
    patient = repository.get_by_id_or_user_id(patient_id)
    if not patient:
        raise AppError("Patient not found", status_code=404, error_type="not_found")
    if current_user.role not in {UserRole.admin, UserRole.front_desk} and current_user.id != patient.user_id:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    if patient.appointments:
        raise AppError(
            "Profiles with appointment history cannot be deleted",
            status_code=409,
            error_type="profile_has_history",
        )
    repository.delete_profile(patient)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
