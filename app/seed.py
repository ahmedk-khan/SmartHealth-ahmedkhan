from datetime import datetime, timedelta, timezone
from sqlalchemy import or_
#seed 
from app.db import SessionLocal
from app.models import Department, Patient, Provider, Service, Slot, SlotStatus, User, UserRole
from app.models import ContentChunk
from app.core.security import get_password_hash
from app.services.embedding_service import generate_embeddings
from app.services.embedding_service import embedding_model_id, generate_embeddings
import asyncio
import hashlib


def seed() -> None:
    db = SessionLocal()

    def ensure_user(email: str, password: str, role: UserRole) -> User:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            if not existing_user.is_active:
                existing_user.is_active = True
                db.commit()
                db.refresh(existing_user)
            return existing_user
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            role=role,
            is_active=True,
        )
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

        if service.is_published and not db.query(ContentChunk).filter(ContentChunk.service_id == service.id).count():
            content = "\n".join((service.description or "", service.preparation_instructions or ""))
            chunks = [content[index : index + 120] for index in range(0, max(len(content), 1), 120)]
            embeddings = asyncio.run(generate_embeddings(chunks))
            model_id = embedding_model_id()
            db.add_all([
                ContentChunk(
                    service_id=service.id,
                    department=department.name,
                    specialty=service.specialty,
                    published=True,
                    source_type="service",
                    source_id=service.id,
                    chunk_index=index,
                    content=chunk,
                    content_hash=hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    token_count=len(chunk.split()),
                    embedding=embedding,
                    embedding_model=model_id,
                )
                for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ])
            db.commit()

        model_id = embedding_model_id()
        stale_chunks = (
            db.query(ContentChunk)
            .join(Service, ContentChunk.service_id == Service.id)
            .filter(
                Service.is_published.is_(True),
                or_(ContentChunk.embedding_model.is_(None), ContentChunk.embedding_model != model_id),
            )
            .all()
        )
        if stale_chunks:
            embeddings = asyncio.run(generate_embeddings([chunk.content for chunk in stale_chunks]))
            for chunk, embedding in zip(stale_chunks, embeddings):
                chunk.embedding = embedding
                chunk.embedding_model = model_id
            db.commit()

        missing_chunks = db.query(Service.id).filter(Service.is_published.is_(True), ~Service.content_chunks.any()).all()
        if missing_chunks:
            raise RuntimeError(f"Published services without content chunks: {[service_id for service_id, in missing_chunks]}")

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
