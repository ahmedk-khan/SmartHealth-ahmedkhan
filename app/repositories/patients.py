from sqlalchemy.orm import Session

from app.models import Patient
from app.repositories.base import BaseRepository


class PatientRepository(BaseRepository):
    def get_by_id_or_user_id(self, patient_id: int) -> Patient | None:
        patient = self.db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            patient = self.db.query(Patient).filter(Patient.user_id == patient_id).first()
        return patient

    def get_by_user_id(self, user_id: int) -> Patient | None:
        return self.db.query(Patient).filter(Patient.user_id == user_id).first()