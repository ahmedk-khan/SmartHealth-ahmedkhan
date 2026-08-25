from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ContentChunk, Department, Service, ServiceStatus
from app.repositories.content_chunks import ContentChunkRepository


def test_replace_for_service_reindexes_vectors_without_duplicates():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        department = Department(name="Cardiology")
        session.add(department)
        session.flush()
        service = Service(
            name="Heart checkup",
            department_id=department.id,
            status=ServiceStatus.PUBLISHED,
            is_published=True,
        )
        session.add(service)
        session.flush()
        repository = ContentChunkRepository(session)

        repository.replace_for_service(
            service.id,
            [
                {"chunk_index": 0, "content": "old one", "department": "Cardiology", "specialty": "Cardiac", "published": True, "embedding": [1.0] * 384},
                {"chunk_index": 1, "content": "old two", "department": "Cardiology", "specialty": "Cardiac", "published": True, "embedding": [1.0] * 384},
            ],
        )
        session.commit()

        repository.replace_for_service(
            service.id,
            [
                {"chunk_index": 0, "content": "new one", "department": "Cardiology", "specialty": "Electrophysiology", "published": True, "embedding": [2.0] * 384},
            ],
        )
        session.commit()

        chunks = session.query(ContentChunk).filter(ContentChunk.service_id == service.id).all()
        assert len(chunks) == 1
        assert chunks[0].content == "new one"
        assert chunks[0].department == "Cardiology"
        assert chunks[0].specialty == "Electrophysiology"
        assert chunks[0].published is True
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_failed_republish_rolls_back_without_partial_chunks():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        department = Department(name="Rollback")
        session.add(department)
        session.flush()
        service = Service(name="Rollback service", department_id=department.id)
        session.add(service)
        session.flush()
        repository = ContentChunkRepository(session)
        vector = [1.0] * 384
        repository.replace_for_service(service.id, [{"chunk_index": 0, "content": "old", "department": "Rollback", "embedding": vector}])
        session.commit()

        repository.replace_for_service(service.id, [{"chunk_index": 0, "content": "new", "department": "Rollback", "embedding": vector}])
        raise RuntimeError("simulated persistence failure")
    except RuntimeError:
        session.rollback()
        assert session.query(ContentChunk).filter(ContentChunk.service_id == service.id).one().content == "old"
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)