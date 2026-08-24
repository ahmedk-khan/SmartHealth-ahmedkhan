from sqlalchemy import or_

from app.models import Appointment, Patient, User
from app.repositories.base import BaseRepository


class PatientRepository(BaseRepository):
    def update_profile(self, patient: Patient, first_name: str | None, last_name: str | None) -> Patient:
        patient.first_name = first_name.strip() if first_name else None
        patient.last_name = last_name.strip() if last_name else None
        self.db.commit()
        self.db.refresh(patient)
        return patient

    def delete_profile(self, patient: Patient) -> None:
        self.db.delete(patient)
        self.db.commit()

    def get_by_id_or_user_id(self, patient_id: int) -> Patient | None:
        patient = self.db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            patient = self.db.query(Patient).filter(Patient.user_id == patient_id).first()
        return patient

    def get_by_user_id(self, user_id: int) -> Patient | None:
        return self.db.query(Patient).filter(Patient.user_id == user_id).first()

    def list_patients(self, offset: int, limit: int, search: str | None = None) -> tuple[list[Patient], int]:
        query = self.db.query(Patient).join(User, Patient.user_id == User.id)
        if search:
            search_term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Patient.first_name.ilike(search_term),
                    Patient.last_name.ilike(search_term),
                    User.email.ilike(search_term),
                )
            )
        total = query.count()
        items = query.order_by(Patient.id).offset(offset).limit(limit).all()
        return items, total

    def list_provider_patients(self, provider_id: int, offset: int, limit: int, search: str | None = None) -> tuple[list[Patient], int]:
        query = self.db.query(Patient).join(User, Patient.user_id == User.id).join(Appointment, Appointment.patient_id == Patient.id).filter(Appointment.provider_id == provider_id).distinct()
        if search:
            search_term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Patient.first_name.ilike(search_term),
                    Patient.last_name.ilike(search_term),
                    User.email.ilike(search_term),
                )
            )
        total = query.count()
        items = query.order_by(Patient.id).offset(offset).limit(limit).all()
        return items, total