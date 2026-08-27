import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ContentChunk, Department, Service, ServiceStatus
from app.services import search_service


def test_search_applies_top_k_threshold_and_published_scope(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        department = Department(name="Search Cardiology")
        session.add(department)
        session.flush()
        services = [
            Service(name="Exact", department_id=department.id, status=ServiceStatus.PUBLISHED, is_published=True, specialty="Cardiac"),
            Service(name="Partial", department_id=department.id, status=ServiceStatus.PUBLISHED, is_published=True, specialty="Vascular"),
            Service(name="Unpublished", department_id=department.id, status=ServiceStatus.UNPUBLISHED, is_published=False),
        ]
        session.add_all(services)
        session.flush()
        vectors = [[1.0] * 1024, [1.0] * 512 + [0.0] * 512, [1.0] * 1024]
        for service, vector in zip(services, vectors):
            session.add(ContentChunk(
                service_id=service.id,
                department=department.name,
                specialty=service.specialty,
                published=True,
                source_type="service",
                source_id=service.id,
                chunk_index=0,
                content=service.name,
                token_count=1,
                embedding=vector,
            ))
        session.commit()

        async def fake_generate_embeddings(texts):
            return [[1.0] * 1024 for _ in texts]

        monkeypatch.setattr(search_service, "generate_embeddings", fake_generate_embeddings)
        from app.core.settings import settings
        monkeypatch.setattr(settings, "retrieval_min_similarity", 0.65)

        results = asyncio.run(search_service.search_services(session, "cardiology", 2))

        assert len(results) == 2
        assert [result["service_name"] for result in results] == ["Exact", "Partial"]
        assert results[0]["department"] == department.name
        assert results[0]["specialty"] == "Cardiac"
        assert not {"patient_id", "appointment_id", "billing_id"}.intersection(results[0])

        monkeypatch.setattr(settings, "retrieval_min_similarity", 1.01)
        assert asyncio.run(search_service.search_services(session, "unrelated", 2)) == []
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
