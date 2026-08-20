from datetime import datetime, timedelta, timezone
#seed 
from app.db import SessionLocal
from app.models import Department, Patient, Provider, Service, Slot, SlotStatus, User, UserRole
from app.core.security import get_password_hash


def seed() -> None:
    db = SessionLocal()

    def ensure_user(email: str, password: str, role: UserRole) -> User:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            return existing_user
        user = User(email=email, hashed_password=get_password_hash(password), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def ensure_department(name: str, description: str) -> Department:
        existing_department = db.query(Department).filter(Department.name == name).first()
        if existing_department:
            return existing_department
        department = Department(name=name, description=description)
        db.add(department)
        db.commit()
        db.refresh(department)
        return department

    try:
        admin = ensure_user("admin@example.com", "secret123", UserRole.admin)
        patient = ensure_user("patient@example.com", "secret123", UserRole.patient)
        provider_user = ensure_user("provider@example.com", "secret123", UserRole.provider)
        demo_admin = ensure_user("demo@gmail.com", "adminadmin", UserRole.admin)

        department = ensure_department("Cardiology", "Heart care")

        provider = db.query(Provider).filter(Provider.user_id == provider_user.id).first()
        if not provider:
            provider = Provider(user_id=provider_user.id, department_id=department.id, bio="Cardiology specialist")
            db.add(provider)
            db.commit()
            db.refresh(provider)

        service = db.query(Service).filter(Service.name == "General Consultation").first()
        if not service:
            service = Service(
                name="General Consultation",
                description="Routine checkup",
                specialty="Primary care",
                preparation_instructions="Bring a list of current medications and relevant medical history.",
                department_id=department.id,
                is_published=True,
            )
            db.add(service)
            db.commit()
            db.refresh(service)

        patient_profile = db.query(Patient).filter(Patient.user_id == patient.id).first()
        if not patient_profile:
            patient_profile = Patient(user_id=patient.id, first_name="Pat", last_name="Patient")
            db.add(patient_profile)
            db.commit()
            db.refresh(patient_profile)

        now = datetime.now(timezone.utc)
        slot = db.query(Slot).filter(Slot.provider_id == provider.id, Slot.service_id == service.id).first()
        if not slot:
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
