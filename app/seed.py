from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Department, Patient, Provider, Service, Slot, SlotStatus, User, UserRole
from app.core.security import get_password_hash


def seed() -> None:
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        admin = User(email="admin@example.com", hashed_password=get_password_hash("secret123"), role=UserRole.admin)
        patient = User(email="patient@example.com", hashed_password=get_password_hash("secret123"), role=UserRole.patient)
        provider_user = User(email="provider@example.com", hashed_password=get_password_hash("secret123"), role=UserRole.provider)
        db.add_all([admin, patient, provider_user])
        db.commit()
        db.refresh(admin)
        db.refresh(patient)
        db.refresh(provider_user)

        department = Department(name="Cardiology", description="Heart care")
        db.add(department)
        db.commit()
        db.refresh(department)

        provider = Provider(user_id=provider_user.id, department_id=department.id, bio="Cardiology specialist")
        db.add(provider)
        db.commit()
        db.refresh(provider)

        service = Service(name="General Consultation", description="Routine checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        patient_profile = Patient(user_id=patient.id, first_name="Pat", last_name="Patient")
        db.add(patient_profile)
        db.commit()
        db.refresh(patient_profile)

        now = datetime.now(timezone.utc)
        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=now + timedelta(days=1),
            end_datetime=now + timedelta(days=1, hours=1),
        )
        db.add(slot)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
