from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models import Patient, User, UserRole
from app.schemas.domain import PatientRead

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/{patient_id}", response_model=PatientRead)
def read_patient(patient_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        patient = db.query(Patient).filter(Patient.user_id == patient_id).first()
    if not patient:
        raise ValueError("Patient not found")
    if current_user.role not in {UserRole.admin, UserRole.front_desk} and current_user.id != patient.user_id:
        raise PermissionError("Forbidden")
    return patient
