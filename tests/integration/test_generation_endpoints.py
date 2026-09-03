"""Integration tests for AI generation endpoints (summary, follow-up, utilisation)."""

import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("REDIS_URL", "memory://")
os.environ["KAFKA_ENABLED"] = "false"

from app.core import dependencies
from app.core.security import get_password_hash
from app.db import Base
from app.main import app
from app.services.llm_provider import FakeLLM
from app.models import (
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


def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data_payload = line[len("data: ") :]
        if data_payload:
            events.append((event_name, json.loads(data_payload)))
    return events


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

    with patch("app.api.v1.endpoints.appointments.get_llm_provider", return_value=FakeLLM()):
        with patch("app.api.v1.endpoints.reports.get_llm_provider", return_value=FakeLLM()):
            with patch.object(app.state.ai_redis_store, "allow_request", new_callable=AsyncMock) as mock_allow:
                mock_allow.return_value = True
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


def _seed_appointment(db):
    patient_user = db.query(User).filter(User.email == "patient@example.com").one()
    provider_user = db.query(User).filter(User.email == "provider@example.com").one()
    patient = _ensure_patient(db, patient_user.id)
    provider = _ensure_provider(db, provider_user.id, bio="General medicine")

    department = Department(name="General", description="Primary care")
    db.add(department)
    db.commit()
    db.refresh(department)

    service = Service(
        name="Annual Checkup",
        description="Routine wellness visit",
        preparation_instructions="Bring insurance card.",
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
    return appointment


def test_summary_generation_streams_structured_sse(client):
    _create_user_record("admin@example.com", "secret123", "admin")
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        appointment = _seed_appointment(db)
        appointment_id = appointment.id
    finally:
        db.close()

    token = _login(client, "admin@example.com", "secret123")
    response = client.post(
        f"/api/v1/appointments/{appointment_id}/generate/summary",
        json={"include_instructions": True, "include_cancellation_policy": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    response_payload = response.json()
    content = response_payload["data"]
    metadata = response_payload["metadata"]

    assert response_payload["success"] is True
    assert content["appointment_id"] == appointment_id
    assert content["service_name"] == "Annual Checkup"
    assert metadata["type"] == "summary"
    assert metadata["appointment_id"] == appointment_id

    db = SessionLocal()
    try:
        generated = db.query(GeneratedContent).one()
        assert generated.type == "summary"
        assert generated.appointment_id == appointment_id
    finally:
        db.close()


def test_followup_generation_streams_structured_sse(client):
    _create_user_record("frontdesk@example.com", "secret123", "front_desk")
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        appointment = _seed_appointment(db)
        appointment_id = appointment.id
    finally:
        db.close()

    token = _login(client, "frontdesk@example.com", "secret123")
    response = client.post(
        f"/api/v1/appointments/{appointment_id}/generate/followup",
        json={"tone": "professional", "include_next_steps": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    response_payload = response.json()
    content = response_payload["data"]
    metadata = response_payload["metadata"]
    assert response_payload["success"] is True

    assert metadata["type"] == "followup"
    assert metadata["appointment_id"] == appointment_id
    assert content["appointment_id"] == appointment_id
    assert content["subject"]
    assert content["body"]
    assert content["recommended_channel"] in {"email", "sms", "in-app"}
    assert content["requires_review"] is True
    assert "[" not in content["subject"] + content["body"]
    assert "[" not in " ".join(content["follow_up_actions"])
    assert content["body"].count("Recommended Next Steps") <= 1
    assert done["ok"] is True
    assert done["content"]["subject"] == content["subject"]


def test_summary_generation_returns_specific_not_found_error(client):
    _create_user_record("admin@example.com", "secret123", "admin")
    token = _login(client, "admin@example.com", "secret123")

    response = client.post(
        "/api/v1/appointments/99999/generate/summary",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert any(name == "error" for name, _ in events)
    done = events[-1][1]
    assert done["ok"] is False
    assert done["error"]["code"] == "APPOINTMENT_NOT_FOUND"
    assert done["error"]["type"] == "not_found"


def test_patient_cannot_generate_summary(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        appointment = _seed_appointment(db)
        appointment_id = appointment.id
    finally:
        db.close()

    token = _login(client, "patient@example.com", "secret123")
    response = client.post(
        f"/api/v1/appointments/{appointment_id}/generate/summary",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "PERMISSION_DENIED"
