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
    Billing,
    BillingStatus,
    ContentChunk,
    Department,
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


def test_list_providers_requires_authentication(client):
    response = client.get("/api/v1/providers")
    assert response.status_code == 401


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


def test_appointment_saga_endpoints_create_state_cancel_and_reschedule(client):
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

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 2, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
        slot_id = slot.id

        replacement_slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 2, 10, 30, tzinfo=timezone.utc),
        )
        db.add(replacement_slot)
        db.commit()
        db.refresh(replacement_slot)
        replacement_slot_id = replacement_slot.id
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    create_response = client.post(
        "/api/v1/appointments",
        json={"slot_id": slot_id},
        headers=patient_headers,
    )
    assert create_response.status_code == 202
    appointment_id = create_response.json()["id"]

    state_response = client.get(f"/api/v1/appointments/{appointment_id}/state", headers=patient_headers)
    assert state_response.status_code == 200
    assert state_response.json()["status"] == "PENDING"

    reschedule_response = client.post(
        f"/api/v1/appointments/{appointment_id}/reschedule",
        json={"slot_id": replacement_slot_id},
        headers=patient_headers,
    )
    assert reschedule_response.status_code == 200
    assert reschedule_response.json()["status"] == "PENDING"

    cancel_response = client.post(f"/api/v1/appointments/{appointment_id}/cancel", headers=patient_headers)
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"

    db = SessionLocal()
    try:
        refreshed_slot = db.query(Slot).filter(Slot.id == slot_id).one()
        refreshed_replacement_slot = db.query(Slot).filter(Slot.id == replacement_slot_id).one()
        assert refreshed_slot.status == SlotStatus.AVAILABLE
        assert refreshed_replacement_slot.status == SlotStatus.AVAILABLE
    finally:
        db.close()


def test_booking_is_idempotent_with_idempotency_key(client):
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
        patient_id = patient.id

        provider = Provider(user_id=provider_user.id, bio="General medicine")
        db.add(provider)
        db.commit()
        db.refresh(provider)

        department = Department(name="Cardiology", description="Heart care")
        db.add(department)
        db.commit()
        db.refresh(department)

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 4, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    headers = {
        "Authorization": f"Bearer {patient_token}",
        "Idempotency-Key": "booking-test-key",
    }

    first = client.post("/api/v1/appointments", json={"slot_id": slot.id}, headers=headers)
    assert first.status_code == 202

    second = client.post("/api/v1/appointments", json={"slot_id": slot.id}, headers=headers)
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]

    db = SessionLocal()
    try:
        appointments = db.query(Appointment).filter(Appointment.patient_id == patient_id).all()
        assert len(appointments) == 1
    finally:
        db.close()


def test_visit_lifecycle_transitions_are_idempotent(client):
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

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 5, 9, 30, tzinfo=timezone.utc),
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
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    first_checkin = client.post(f"/api/v1/appointments/{appointment.id}/visit/check-in", headers=patient_headers)
    assert first_checkin.status_code == 200
    assert first_checkin.json()["visit_status"] == "CHECKED_IN"

    repeated_checkin = client.post(f"/api/v1/appointments/{appointment.id}/visit/check-in", headers=patient_headers)
    assert repeated_checkin.status_code == 200
    assert repeated_checkin.json()["visit_status"] == "CHECKED_IN"

    start = client.post(f"/api/v1/appointments/{appointment.id}/visit/start", headers=patient_headers)
    assert start.status_code == 200
    assert start.json()["visit_status"] == "IN_PROGRESS"

    complete = client.post(f"/api/v1/appointments/{appointment.id}/visit/complete", headers=patient_headers)
    assert complete.status_code == 200
    assert complete.json()["visit_status"] == "COMPLETED"


def test_billing_precheck_is_idempotent(client):
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

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
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
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    first = client.post(f"/api/v1/appointments/{appointment.id}/billing/pre-check", headers=patient_headers)
    assert first.status_code == 200
    assert first.json()["status"] == BillingStatus.APPROVED.value

    second = client.post(f"/api/v1/appointments/{appointment.id}/billing/pre-check", headers=patient_headers)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    db = SessionLocal()
    try:
        records = db.query(Billing).filter(Billing.appointment_id == appointment.id).all()
        assert len(records) == 1
    finally:
        db.close()


def test_slot_reservation_prevents_double_booking(client):
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

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 6, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    headers = {"Authorization": f"Bearer {patient_token}"}

    first = client.post(f"/api/v1/slots/{slot.id}/reserve", headers=headers)
    assert first.status_code == 200

    second = client.post(f"/api/v1/slots/{slot.id}/reserve", headers=headers)
    assert second.status_code == 409


def test_duplicate_booking_is_rejected(client):
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

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 7, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    headers = {"Authorization": f"Bearer {patient_token}"}

    first = client.post("/api/v1/appointments", json={"slot_id": slot.id}, headers=headers)
    assert first.status_code == 202

    second = client.post("/api/v1/appointments", json={"slot_id": slot.id}, headers=headers)
    assert second.status_code == 409


def test_saga_compensation_releases_slot_on_failure(client):
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

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    headers = {"Authorization": f"Bearer {patient_token}"}

    response = client.post(
        "/api/v1/appointments",
        json={"slot_id": slot.id, "force_failure": True},
        headers=headers,
    )
    assert response.status_code == 500

    db = SessionLocal()
    try:
        refreshed_slot = db.query(Slot).filter(Slot.id == slot.id).one()
        assert refreshed_slot.status == SlotStatus.AVAILABLE
    finally:
        db.close()


def test_service_publish_rejects_illegal_state_transitions(client):
    _create_user(client, "admin@example.com", "secret123", "admin")
    admin_token = _login(client, "admin@example.com", "secret123")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        department = Department(name="Neurology", description="Brain care")
        db.add(department)
        db.commit()
        db.refresh(department)

        service = Service(name="MRI", department_id=department.id, status=ServiceStatus.PUBLISHING, is_published=False)
        db.add(service)
        db.commit()
        db.refresh(service)
        service_id = service.id
    finally:
        db.close()

    publish_response = client.post(f"/api/v1/services/{service_id}/publish", headers=admin_headers)
    assert publish_response.status_code == 409


def test_visit_illegal_transition_is_rejected(client):
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

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.commit()
        db.refresh(service)

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 9, 9, 30, tzinfo=timezone.utc),
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
    finally:
        db.close()

    patient_token = _login(client, "patient@example.com", "secret123")
    headers = {"Authorization": f"Bearer {patient_token}"}

    response = client.post(f"/api/v1/appointments/{appointment.id}/visit/complete", headers=headers)
    assert response.status_code == 409


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
