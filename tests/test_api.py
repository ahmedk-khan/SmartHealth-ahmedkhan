import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core import dependencies
from app.db import Base
from app.main import app
from app.models import (
    Appointment,
    AppointmentStatus,
    AppointmentStatusHistory,
    ContentChunk,
    Department,
    Patient,
    Provider,
    Service,
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
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    from app import db as db_module

    db_module.engine = engine
    db_module.SessionLocal = TestingSessionLocal
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _create_user(client, email, password, role):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password, "role": role},
    )
    assert response.status_code == 200
    return response.json()


def _login(client, email, password):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_register_login_and_invalid_token(client):
    _create_user(client, "alice@example.com", "secret123", "patient")

    token = _login(client, "alice@example.com", "secret123")
    headers = {"Authorization": f"Bearer {token}"}

    protected = client.get("/api/v1/departments", headers=headers)
    assert protected.status_code == 200

    invalid = client.get("/api/v1/departments", headers={"Authorization": "Bearer invalid"})
    assert invalid.status_code == 401


def test_patient_cannot_access_provider_schedule_or_other_patient_data(client):
    admin = _create_user(client, "admin@example.com", "secret123", "admin")
    patient_user = _create_user(client, "patient@example.com", "secret123", "patient")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        patient = Patient(user_id=patient_user["id"])
        db.add(patient)
        db.commit()
        db.refresh(patient)
        patient_id = patient.id

        provider_user = User(email="provider@example.com", hashed_password="x", role=UserRole.provider)
        db.add(provider_user)
        db.commit()
        db.refresh(provider_user)

        provider = Provider(user_id=provider_user.id, bio="General medicine")
        db.add(provider)
        db.commit()
        db.refresh(provider)

        department = Department(name="Cardiology", description="Heart care")
        db.add(department)
        db.commit()
        db.refresh(department)

        service = Service(name="Checkup", description="Routine visit", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
    finally:
        db.close()

    other_patient_user = _create_user(client, "other@example.com", "secret123", "patient")
    other_patient = Patient(user_id=other_patient_user["id"])
    db = SessionLocal()
    try:
        db.add(other_patient)
        db.commit()
        db.refresh(other_patient)
        other_patient_id = other_patient.id
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    forbidden_schedule = client.get("/api/v1/providers/1/slots", headers=patient_headers)
    assert forbidden_schedule.status_code == 403

    forbidden_patient_data = client.get(f"/api/v1/patients/{other_patient_id}", headers=patient_headers)
    assert forbidden_patient_data.status_code == 403


def test_staff_can_create_and_list_services_with_public_filters(client):
    _create_user(client, "admin@example.com", "secret123", "admin")
    _create_user(client, "patient@example.com", "secret123", "patient")
    admin_token = _login(client, "admin@example.com", "secret123")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    department_response = client.post(
        "/api/v1/departments",
        json={"name": "Neurology", "description": "Brain health"},
        headers=admin_headers,
    )
    assert department_response.status_code == 200
    department_id = department_response.json()["id"]

    service_response = client.post(
        "/api/v1/services",
        json={"name": "MRI Scan", "description": "MRI diagnostic", "department_id": department_id, "is_published": True},
        headers=admin_headers,
    )
    assert service_response.status_code == 200

    patient_token = _login(client, "patient@example.com", "secret123")
    patient_headers = {"Authorization": f"Bearer {patient_token}"}
    public_response = client.get("/api/v1/public/services?search=MRI", headers=patient_headers)
    assert public_response.status_code == 200
    data = public_response.json()
    assert data["total"] >= 1
    assert data["items"][0]["name"] == "MRI Scan"


def test_appointment_and_status_history_are_created_for_slot(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        patient_user = db.query(User).filter(User.email == "patient@example.com").one()
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()

        patient = Patient(user_id=patient_user.id)
        db.add(patient)
        db.commit()
        db.refresh(patient)

        provider = Provider(user_id=provider_user.id, bio="General medicine")
        db.add(provider)
        db.commit()
        db.refresh(provider)

        department = Department(name="Cardiology", description="Heart care")
        db.add(department)
        db.commit()
        db.refresh(department)

        service = Service(
            name="Checkup",
            description="Routine visit",
            department_id=department.id,
            is_published=True,
        )
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)

        appointment = Appointment(
            patient_id=patient.id,
            provider_id=provider.id,
            service_id=service.id,
            slot_id=slot.id,
            status=AppointmentStatus.PENDING,
        )
        db.add(appointment)
        db.commit()
        db.refresh(appointment)
        appointment_id = appointment.id

        history_entry = AppointmentStatusHistory(appointment_id=appointment_id, status=appointment.status)
        db.add(history_entry)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        stored = db.query(Appointment).filter(Appointment.id == appointment_id).one()
        assert stored.status == AppointmentStatus.PENDING
        assert len(stored.status_history) == 1
        assert stored.status_history[0].status == AppointmentStatus.PENDING
    finally:
        db.close()


def test_duplicate_registration_is_rejected(client):
    first = _create_user(client, "dup@example.com", "secret123", "patient")
    assert first["email"] == "dup@example.com"

    second = client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "another", "role": "patient"},
    )
    assert second.status_code == 400


def test_service_publish_starts_workflow_and_writes_chunks(client):
    _create_user(client, "admin@example.com", "secret123", "admin")
    admin_token = _login(client, "admin@example.com", "secret123")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    department_response = client.post(
        "/api/v1/departments",
        json={"name": "Neurology", "description": "Brain health"},
        headers=admin_headers,
    )
    assert department_response.status_code == 200
    department_id = department_response.json()["id"]

    service_response = client.post(
        "/api/v1/services",
        json={"name": "MRI Scan", "description": "MRI diagnostic", "department_id": department_id, "is_published": False},
        headers=admin_headers,
    )
    assert service_response.status_code == 200
    service_id = service_response.json()["id"]

    publish_response = client.post(f"/api/v1/services/{service_id}/publish", headers=admin_headers)
    assert publish_response.status_code == 202
    publish_payload = publish_response.json()
    assert publish_payload["workflow_id"] == f"service-publish-{service_id}"

    status_response = client.get(f"/api/v1/services/{service_id}/publish-status", headers=admin_headers)
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["workflow_id"] == f"service-publish-{service_id}"
    assert status_payload["status"] in {"PUBLISHING", "PUBLISHED"}

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        service = db.query(Service).filter(Service.id == service_id).first()
        assert service is not None
        assert service.status == "PUBLISHED"
        assert service.is_published is True
        assert db.query(ContentChunk).filter(ContentChunk.service_id == service_id).count() >= 1
    finally:
        db.close()
