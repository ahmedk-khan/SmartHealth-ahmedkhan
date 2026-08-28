from datetime import datetime, timedelta, timezone
import logging
#seed 
from app.db import SessionLocal
from app.models import Department, Patient, Provider, Service, Slot, SlotStatus, User, UserRole
from app.models import ContentChunk
from app.core.security import get_password_hash
from app.core.settings import settings
from app.services.embedding_service import generate_embeddings
from app.services.embedding_service import embedding_model_id, generate_embeddings
from app.repositories import AuthRepository, ContentChunkRepository, DepartmentRepository, PatientRepository, ProviderRepository, ServiceRepository, SlotRepository
import asyncio
import hashlib

logger = logging.getLogger(__name__)


def seed() -> None:
    if settings.app_env.lower() in {"production", "prod"}:
        logger.warning("Seed operation skipped because APP_ENV is production")
        return

    db = SessionLocal()
    users = AuthRepository(db)
    departments = DepartmentRepository(db)
    providers = ProviderRepository(db)
    services = ServiceRepository(db)
    patients = PatientRepository(db)
    slots = SlotRepository(db)
    chunks_repository = ContentChunkRepository(db)

    def ensure_user(email: str, password: str, role: UserRole) -> User:
        return users.ensure_seed_user(email, get_password_hash(password), role)

    def ensure_department(name: str, description: str) -> Department:
        existing_department = departments.get_by_name(name)
        if existing_department:
            return existing_department
        return departments.create_department(name, description)

    try:
        admin = ensure_user("admin@example.com", "secret123", UserRole.admin)
        patient = ensure_user("patient@example.com", "secret123", UserRole.patient)
        provider_user = ensure_user("provider@example.com", "secret123", UserRole.provider)
        demo_admin = ensure_user("demo@gmail.com", "adminadmin", UserRole.admin)

        department = ensure_department("Cardiology", "Heart care")

        provider = providers.get_by_user_id(provider_user.id)
        if not provider:
            provider = providers.create_seed_provider(provider_user.id, department.id, "Cardiology specialist")

        service = services.get_by_name("General Consultation")
        if not service:
            service = Service(
                name="General Consultation",
                description="Routine checkup",
                specialty="Primary care",
                preparation_instructions="Bring a list of current medications and relevant medical history.",
                department_id=department.id,
                is_published=True,
            )
            service = services.create_seed_service({
                "name": "General Consultation",
                "description": "Routine checkup",
                "specialty": "Primary care",
                "preparation_instructions": "Bring a list of current medications and relevant medical history.",
                "department_id": department.id,
                "is_published": True,
            })

        if service.is_published and not chunks_repository.count_for_service(service.id):
            content = "\n".join((service.description or "", service.preparation_instructions or ""))
            chunks = [content[index : index + 120] for index in range(0, max(len(content), 1), 120)]
            embeddings = asyncio.run(generate_embeddings(chunks))
            model_id = embedding_model_id()
            chunks_repository.create_seed_chunks([
                {
                    "service_id": service.id,
                    "department": department.name,
                    "specialty": service.specialty,
                    "published": True,
                    "source_type": "service",
                    "source_id": service.id,
                    "chunk_index": index,
                    "content": chunk,
                    "content_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    "token_count": len(chunk.split()),
                    "embedding": embedding,
                    "embedding_model": model_id,
                }
                for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ])

        model_id = embedding_model_id()
        stale_chunks = chunks_repository.list_stale_published_chunks(model_id)
        if stale_chunks:
            embeddings = asyncio.run(generate_embeddings([chunk.content for chunk in stale_chunks]))
            chunks_repository.update_embeddings(stale_chunks, embeddings, model_id)

        missing_chunks = services.published_without_chunks()
        if missing_chunks:
            raise RuntimeError(f"Published services without content chunks: {[service_id for service_id, in missing_chunks]}")

        patient_profile = patients.get_by_user_id(patient.id)
        if not patient_profile:
            patient_profile = patients.create_seed_profile(patient.id, "Pat", "Patient")

        now = datetime.now(timezone.utc)
        slot = slots.get_by_provider_and_service(provider.id, service.id)
        if not slot:
            slots.create_seed_slot({
                "provider_id": provider.id,
                "service_id": service.id,
                "status": SlotStatus.AVAILABLE,
                "start_datetime": now + timedelta(days=1),
                "end_datetime": now + timedelta(days=1, hours=1),
            })
    finally:
        db.close()


if __name__ == "__main__":
    seed()
