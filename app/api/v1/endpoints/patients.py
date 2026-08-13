from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppError
from app.models import User, UserRole
from app.repositories import PatientRepository
from app.schemas.domain import PatientRead

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/{patient_id}", response_model=PatientRead)
def read_patient(patient_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    repository = PatientRepository(db)
    patient = repository.get_by_id_or_user_id(patient_id)
    if not patient:
        raise AppError("Patient not found", status_code=404, error_type="not_found")
    if current_user.role not in {UserRole.admin, UserRole.front_desk} and current_user.id != patient.user_id:
        raise AppError("Forbidden", status_code=403, error_type="forbidden")
    return patient
