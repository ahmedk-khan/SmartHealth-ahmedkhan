import asyncio
from datetime import datetime, timezone
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core import dependencies
from app.core.security import get_password_hash
from app.db import Base
from app.main import app
from app.models import (
    AIInteraction,
    Appointment,
    AppointmentStatus,
    Department,
    GeneratedContent,
    Patient,
    Provider,
    Service,
    ServiceStatus,
    Slot,
    SlotStatus,
    User,
    UserRole,
)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    from app import db as db_module

    db_module.engine = engine
    db_module.SessionLocal = testing_session
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _create_user(client, email, password, role):
    response = client.post("/auth/register", json={"email": email, "password": password, "role": role})
    assert response.status_code == 200
    return response.json()


def _create_user_record(email, password, role):
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        user = User(email=email, hashed_password=get_password_hash(password), role=UserRole(role))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _login(client, email, password):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _ensure_patient(db, user_id):
    patient = db.query(Patient).filter(Patient.user_id == user_id).one_or_none()
    if patient is None:
        patient = Patient(user_id=user_id)
        db.add(patient)
        db.commit()
        db.refresh(patient)
    return patient


def _ensure_provider(db, user_id, bio=None):
    provider = db.query(Provider).filter(Provider.user_id == user_id).one_or_none()
    if provider is None:
        provider = Provider(user_id=user_id, bio=bio)
        db.add(provider)
    elif bio is not None and provider.bio is None:
        provider.bio = bio
    db.commit()
    db.refresh(provider)
    return provider


def _seed_service(db, provider, name="MRI Scan"):
    department = Department(name="Radiology", description="Imaging")
    db.add(department)
    db.commit()
    db.refresh(department)

    service = Service(
        name=name,
        description="Diagnostic imaging",
        preparation_instructions="Bring prior imaging reports.",
        department_id=department.id,
        status=ServiceStatus.PUBLISHED,
        is_published=True,
    )
    db.add(service)
    db.commit()
    db.refresh(service)

    slot = Slot(
        provider_id=provider.id,
        service_id=service.id,
        status=SlotStatus.AVAILABLE,
        start_datetime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc),
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return department, service, slot


def test_assistant_refuses_diagnosis_and_persists_refusal(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    token = _login(client, "patient@example.com", "secret123")

    response = client.post(
        "/assistant/ask",
        json={"question": "Diagnose me: I have knee pain. What caused it and what medication should I take?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    response_data = response.json()
    assert response_data["success"] is True
    assert "I can't provide medical advice" in response_data["data"]["answer"]
    assert response_data["data"]["refused"] is True

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(AIInteraction).all()
        assert len(rows) == 1
        interaction = rows[0]
        assert interaction.refused is True
        assert interaction.question.startswith("sha256:")
        assert interaction.retrieved_ids == []
        assert "medical advice" in interaction.answer.lower()
        assert interaction.latency_ms is not None
    finally:
        db.close()


def test_assistant_stream_route_preserves_sse_contract(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    token = _login(client, "patient@example.com", "secret123")

    response = client.post(
        "/assistant/ask/stream",
        json={"question": "Diagnose me"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: text" in response.text
    assert "event: done" in response.text


def test_assistant_rejects_empty_and_gibberish_input(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    token = _login(client, "patient@example.com", "secret123")

    empty_response = client.post(
        "/assistant/ask",
        json={"question": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    gibberish_response = client.post(
        "/assistant/ask",
        json={"question": "asdfghjklqwerty"},
        headers={"Authorization": f"Bearer {token}"},
    )
    oversized_response = client.post(
        "/assistant/ask",
        json={"question": "x" * 2001},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert empty_response.status_code == 422
    assert gibberish_response.status_code == 422
    assert oversized_response.status_code == 422
    assert empty_response.status_code != 500
    assert gibberish_response.status_code != 500
    assert oversized_response.status_code != 500


def test_preparation_and_availability_are_grounded_in_real_data(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")
    patient_token = _login(client, "patient@example.com", "secret123")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()
        provider = _ensure_provider(db, provider_user.id, bio="General medicine")
        _seed_service(db, provider)
    finally:
        db.close()

    prep_response = client.post(
        "/assistant/ask",
        json={"question": "How should I prepare for the MRI scan?"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    availability_response = client.post(
        "/assistant/ask",
        json={"question": "When is the MRI scan available?"},
        headers={"Authorization": f"Bearer {patient_token}"},
    )

    assert prep_response.status_code == 200
    assert "Bring prior imaging reports." in prep_response.text
    assert availability_response.status_code == 200
    assert "available slot" in availability_response.text.lower()
    assert "2026-08-10 09:00 UTC" in availability_response.text


def test_availability_followup_uses_the_previous_service_topic(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")
    patient_token = _login(client, "patient@example.com", "secret123")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()
        provider = _ensure_provider(db, provider_user.id, bio="Cardiology")
        department = Department(name="Cardiology", description="Heart care")
        db.add(department)
        db.commit()
        db.refresh(department)
        service = Service(
            name="Cardiology Consultation",
            description="Heart consultation for cardiac concerns",
            preparation_instructions="Bring prior imaging reports.",
            department_id=department.id,
            specialty="Cardiology",
            status=ServiceStatus.PUBLISHED,
            is_published=True,
        )
        db.add(service)
        db.commit()
        db.refresh(service)
        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
    finally:
        db.close()

    conversation_id = str(uuid4())
    headers = {"Authorization": f"Bearer {patient_token}"}
    service_response = client.post(
        "/assistant/ask",
        json={"question": "What service do you offer related to heart?", "conversation_id": conversation_id},
        headers=headers,
    )
    assert service_response.status_code == 200
    assert "Available services:" not in service_response.json()["data"]["answer"]

    availability_response = client.post(
        "/assistant/ask",
        json={"question": "Any slots avialbe?", "conversation_id": conversation_id},
        headers=headers,
    )

    assert availability_response.status_code == 200
    assert "Cardiology Consultation" in availability_response.text
    assert "available slot" in availability_response.text.lower()


def test_availability_followup_reuses_recent_retrieved_ids_without_conversation_id(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")
    patient_token = _login(client, "patient@example.com", "secret123")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()
        provider = _ensure_provider(db, provider_user.id, bio="Cardiology")
        department = Department(name="Cardiology", description="Heart care")
        db.add(department)
        db.commit()
        db.refresh(department)
        service = Service(
            name="General Consultation",
            description="Heart consultations and cardiology OPD",
            preparation_instructions="Bring prior imaging reports.",
            department_id=department.id,
            specialty="Cardiology",
            status=ServiceStatus.PUBLISHED,
            is_published=True,
        )
        db.add(service)
        db.commit()
        db.refresh(service)
        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {patient_token}"}
    first = client.post(
        "/assistant/ask",
        json={"question": "i want kwno do you offer heart conslulatins explain please"},
        headers=headers,
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert "Available services:" not in first_payload["answer"]
    assert "General Consultation" in first_payload["answer"] or any(
        c.get("service_name") == "General Consultation" for c in first_payload["citations"]
    )

    second = client.post(
        "/assistant/ask",
        json={"question": "also any slots avialble"},
        headers=headers,
    )
    assert second.status_code == 200
    second_answer = second.json()["data"]["answer"]
    assert "we don't offer that" not in second_answer.lower()
    assert "General Consultation" in second_answer
    assert "available slot" in second_answer.lower()


def test_assistant_uses_only_the_authenticated_users_appointments(client):
    _create_user(client, "patient-one@example.com", "secret123", "patient")
    _create_user(client, "patient-two@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        patient_one_user = db.query(User).filter(User.email == "patient-one@example.com").one()
        patient_two_user = db.query(User).filter(User.email == "patient-two@example.com").one()
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()
        patient_one = _ensure_patient(db, patient_one_user.id)
        patient_two = _ensure_patient(db, patient_two_user.id)
        provider = _ensure_provider(db, provider_user.id, bio="General medicine")
        _department, service, slot_one = _seed_service(db, provider, name="General Checkup")
        slot_two = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 11, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot_two)
        db.commit()
        db.refresh(slot_two)

        appointment_one = Appointment(
            patient_id=patient_one.id,
            provider_id=provider.id,
            service_id=service.id,
            slot_id=slot_one.id,
            status=AppointmentStatus.CONFIRMED,
        )
        appointment_two = Appointment(
            patient_id=patient_two.id,
            provider_id=provider.id,
            service_id=service.id,
            slot_id=slot_two.id,
            status=AppointmentStatus.CONFIRMED,
        )
        db.add_all([appointment_one, appointment_two])
        db.commit()
        db.refresh(appointment_one)
        db.refresh(appointment_two)
    finally:
        db.close()

    token = _login(client, "patient-one@example.com", "secret123")
    response = client.post(
        "/assistant/ask",
        json={"question": "What is my appointment status?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert str(appointment_one.id) in response.text
    assert str(appointment_two.id) not in response.text


def test_utilisation_report_streams_and_uses_analytics(client):
    _create_user_record("admin@example.com", "secret123", "admin")
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == "admin@example.com").one()
        patient_user = db.query(User).filter(User.email == "patient@example.com").one()
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()
        patient = _ensure_patient(db, patient_user.id)
        provider = _ensure_provider(db, provider_user.id, bio="General medicine")
        _department, service, slot = _seed_service(db, provider, name="Annual Checkup")
        appointment = Appointment(
            patient_id=patient.id,
            provider_id=provider.id,
            service_id=service.id,
            slot_id=slot.id,
            status=AppointmentStatus.CONFIRMED,
        )
        db.add(appointment)
        db.commit()
        db.refresh(appointment)
    finally:
        db.close()

    token = _login(client, "admin@example.com", "secret123")
    response = client.post(
        "/api/v1/reports/generate/utilisation/stream",
        json={"period_start": "2026-08-01", "period_end": "2026-08-31"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: citations" in response.text
    assert "event: done" in response.text
    assert '"appointments_booked": 1' in response.text
    assert '"total_patients": 1' in response.text
    assert response.text.rfind("event: text") < response.text.find("event: citations") < response.text.find("event: done")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        generated_rows = db.query(GeneratedContent).all()
        assert len(generated_rows) == 1
        generated = generated_rows[0]
        assert generated.type == "utilisation_report"
        assert generated.report_scope == "2026-08-01..2026-08-31"
        assert generated.prompt_version == "PROMPT_REPORT_V1"
        assert generated.model is not None
        assert generated.content["appointments_booked"] == 1
        assert generated.content["total_patients"] == 1
    finally:
        db.close()


def test_long_report_generation_does_not_block_booking(client, monkeypatch):
    _create_user(client, "patient-book@example.com", "secret123", "patient")
    _create_user(client, "provider-book@example.com", "secret123", "provider")
    _create_user_record("admin-book@example.com", "secret123", "admin")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        patient_user = db.query(User).filter(User.email == "patient-book@example.com").one()
        provider_user = db.query(User).filter(User.email == "provider-book@example.com").one()
        patient = _ensure_patient(db, patient_user.id)
        provider = _ensure_provider(db, provider_user.id, bio="General medicine")
        _department, service, slot = _seed_service(db, provider, name="Vaccination")
        booking_slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc),
        )
        db.add(booking_slot)
        db.commit()
        db.refresh(booking_slot)
        appointment = Appointment(
            patient_id=patient.id,
            provider_id=provider.id,
            service_id=service.id,
            slot_id=slot.id,
            status=AppointmentStatus.CONFIRMED,
        )
        db.add(appointment)
        db.commit()
    finally:
        db.close()

    class SlowLLM:
        async def stream(self, prompt: str):
            yield "summary "
            yield "content "

        async def complete_json(self, prompt: str) -> str:
            await asyncio.sleep(2)
            return (
                '{"period_start":"2026-08-01","period_end":"2026-08-31",'
                '"appointments_booked":0,"completed_visits":0,"cancellations":0,'
                '"total_patients":0,"failed_workflows":0}'
            )

    import app.services.assistant_service as assistant_service_module

    monkeypatch.setattr(assistant_service_module, "get_llm_provider", lambda: SlowLLM())

    token = _login(client, "admin-book@example.com", "secret123")
    report_done = threading.Event()

    def run_report():
        response = client.post(
            "/api/v1/reports/generate/utilisation",
            json={"period_start": "2026-08-01", "period_end": "2026-08-31"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        report_done.set()
        return response

    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(run_report)
        time.sleep(0.2)
        booking_token = _login(client, "patient-book@example.com", "secret123")
        booking_started = time.perf_counter()
        booking_response = client.post(
            "/api/v1/appointments",
            json={"slot_id": booking_slot.id},
            headers={"Authorization": f"Bearer {booking_token}"},
        )
        booking_elapsed = time.perf_counter() - booking_started
        assert booking_response.status_code == 202
        assert booking_elapsed < 1.0
        assert report_done.wait(timeout=5) is True
        response = future.result(timeout=5)

    assert response.status_code == 200
    assert "event: text" in response.text
    assert "event: citations" in response.text
    assert "event: done" in response.text
