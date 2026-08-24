import asyncio
import os
from datetime import datetime, timezone

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
from app.workflows.service_publish import chunk_service


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


def _create_user_record(email, password, role, first_name=None, last_name=None):
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            role=UserRole(role),
        )
        db.add(user)
        db.flush()
        if role == "patient":
            db.add(Patient(user_id=user.id, first_name=first_name, last_name=last_name))
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
    if patient is not None:
        return patient
    patient = Patient(user_id=user_id)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def test_chunk_service_includes_service_context():
    chunks = asyncio.run(
        chunk_service(
        {
            "title": "MRI Scan",
            "department_name": "Radiology",
            "specialty": "Musculoskeletal imaging",
            "preparation_instructions": "Avoid metal accessories before the scan.",
            "description": "A diagnostic imaging service.",
        }
        )
    )

    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert "Service: MRI Scan" in chunks[0]["content"]
    assert "Department: Radiology" in chunks[0]["content"]
    assert "Specialty: Musculoskeletal imaging" in chunks[0]["content"]
    assert "Preparation instructions: Avoid metal accessories before the scan." in chunks[0]["content"]
    assert "A diagnostic imaging service." in chunks[0]["content"]


def test_register_login_and_invalid_token(client):
    _create_user(client, "alice@example.com", "secret123", "patient")

    token = _login(client, "alice@example.com", "secret123")
    headers = {"Authorization": f"Bearer {token}"}

    protected = client.get("/api/v1/departments", headers=headers)
    assert protected.status_code == 200

    invalid = client.get("/api/v1/departments", headers={"Authorization": "Bearer invalid"})
    assert invalid.status_code == 401


def test_patient_register_creates_profile_and_can_reserve_slot(client):
    _create_user(client, "provider@example.com", "secret123", "provider")
    _create_user(client, "patient2@example.com", "secret123", "patient")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        patient_user = db.query(User).filter(User.email == "patient2@example.com").one()
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()

        patient_profile = db.query(Patient).filter(Patient.user_id == patient_user.id).one_or_none()
        assert patient_profile is not None

        provider = Provider(user_id=provider_user.id, bio="General medicine")
        db.add(provider)
        db.commit()
        db.refresh(provider)

        department = Department(name="Dermatology", description="Skin care")
        db.add(department)
        db.commit()
        db.refresh(department)

        service = Service(name="Skin Check", department_id=department.id, is_published=True)
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
        slot_id = slot.id
    finally:
        db.close()

    patient_token = _login(client, "patient2@example.com", "secret123")
    headers = {"Authorization": f"Bearer {patient_token}"}
    reserve_response = client.post(f"/api/v1/slots/{slot_id}/reserve", headers=headers)
    assert reserve_response.status_code == 200
    assert reserve_response.json()["status"] == "RESERVED"


def test_patient_cannot_access_provider_schedule_or_other_patient_data(client):
    admin = _create_user_record("admin@example.com", "secret123", "admin")
    patient_user = _create_user(client, "patient@example.com", "secret123", "patient")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        patient = _ensure_patient(db, patient_user["id"])
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
    db = SessionLocal()
    try:
        other_patient = _ensure_patient(db, other_patient_user["id"])
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


def test_operational_endpoints_require_authentication(client):
    assert client.get("/api/v1/analytics/summary").status_code == 401
    assert client.get("/api/v1/analytics/reconcile").status_code == 401
    assert client.get("/api/v1/tasks/example-task").status_code == 401


def test_admin_can_list_and_search_patients(client):
    _create_user_record("admin@example.com", "secret123", "admin")
    _create_user(client, "alice@example.com", "secret123", "patient")
    _create_user(client, "bob@example.com", "secret123", "patient")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        alice = db.query(User).filter(User.email == "alice@example.com").one()
        bob = db.query(User).filter(User.email == "bob@example.com").one()

        _ensure_patient(db, alice.id)
        patient = _ensure_patient(db, bob.id)
        patient.first_name = "Bob"
        patient.last_name = "Johnson"
        db.commit()
    finally:
        db.close()

    admin_token = _login(client, "admin@example.com", "secret123")
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.get("/api/v1/patients?limit=10&offset=0&search=Bob", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["total"] >= 1
    assert any(item["first_name"] == "Bob" for item in data["items"])


def test_admin_can_provision_existing_provider_user(client):
    _create_user_record("admin@example.com", "secret123", "admin")
    provider_user = _create_user(client, "doctor@example.com", "secret123", "provider")

    admin_token = _login(client, "admin@example.com", "secret123")
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.post(
        "/api/v1/providers",
        json={"user_id": provider_user["id"], "specialty": "Cardiology"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == provider_user["id"]


def test_provider_can_update_own_profile_using_user_id_or_provider_id(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    provider_user = _create_user(client, "doctor@example.com", "secret123", "provider")

    provider_token = _login(client, "doctor@example.com", "secret123")
    provider_headers = {"Authorization": f"Bearer {provider_token}"}

    create_response = client.post(
        "/api/v1/providers",
        json={"bio": "General medicine", "specialty": "Cardiology"},
        headers=provider_headers,
    )
    assert create_response.status_code == 200
    provider = create_response.json()

    assert provider["user_id"] == provider_user["id"]
    assert provider["id"] != provider_user["id"]

    update_by_user_id = client.patch(
        f"/api/v1/providers/{provider_user['id']}",
        json={"bio": "Updated bio"},
        headers=provider_headers,
    )
    assert update_by_user_id.status_code == 200
    assert update_by_user_id.json()["bio"] == "Updated bio"

    update_by_provider_id = client.patch(
        f"/api/v1/providers/{provider['id']}",
        json={"specialty": "Family medicine"},
        headers=provider_headers,
    )
    assert update_by_provider_id.status_code == 200
    assert update_by_provider_id.json()["specialty"] == "Family medicine"


def test_staff_can_create_and_list_services_with_public_filters(client):
    _create_user_record("admin@example.com", "secret123", "admin")
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

        patient = _ensure_patient(db, patient_user.id)

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

        patient = _ensure_patient(db, patient_user.id)

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
    assert state_response.json()["status"] == "CONFIRMED"

    reschedule_response = client.post(
        f"/api/v1/appointments/{appointment_id}/reschedule",
        json={"slot_id": replacement_slot_id},
        headers=patient_headers,
    )
    assert reschedule_response.status_code == 200
    assert reschedule_response.json()["status"] == "SLOT_RESERVED"

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

        patient = _ensure_patient(db, patient_user.id)
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

        patient = _ensure_patient(db, patient_user.id)

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

        patient = _ensure_patient(db, patient_user.id)

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
    assert first.json()["status"] == BillingStatus.PENDING.value

    second = client.post(f"/api/v1/appointments/{appointment.id}/billing/pre-check", headers=patient_headers)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    db = SessionLocal()
    try:
        records = db.query(Billing).filter(Billing.appointment_id == appointment.id).all()
        assert len(records) == 1
    finally:
        db.close()


def test_analytics_consumer_deduplicates_replayed_visit_completed_event(client):
    from app.db import SessionLocal
    from app.models import AnalyticsAppointmentDaily, AnalyticsProcessedEvent
    from app.workers.analytics_consumer import AnalyticsConsumer

    consumer = AnalyticsConsumer()
    payload = {
        "event_id": "evt-visit-completed-001",
        "event_type": "visit.completed",
        "occurred_at": "2026-08-15T10:00:00Z",
        "source": "smarthealth-api",
        "entity_type": "appointment",
        "entity_id": "42",
        "appointment_id": 42,
        "patient_id": 7,
        "provider_id": 9,
        "service_id": 12,
        "slot_id": 18,
        "visit_status": "COMPLETED",
        "status": "CONFIRMED",
    }

    consumer.process_message(payload, "app.appointment.visit_status_changed")
    consumer.process_message(payload, "app.appointment.visit_status_changed")

    db = SessionLocal()
    try:
        processed_count = db.query(AnalyticsProcessedEvent).filter(AnalyticsProcessedEvent.event_id == payload["event_id"]).count()
        completed_rows = db.query(AnalyticsAppointmentDaily).filter(
            AnalyticsAppointmentDaily.event_type == "visit.completed",
        ).count()
        assert processed_count == 1
        assert completed_rows == 1
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

        patient = _ensure_patient(db, patient_user.id)

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

        patient = _ensure_patient(db, patient_user.id)

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

        patient = _ensure_patient(db, patient_user.id)

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
    _create_user_record("admin@example.com", "secret123", "admin")
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


def test_service_list_handles_failed_publish_status(client):
    _create_user_record("admin@example.com", "secret123", "admin")
    _create_user(client, "patient@example.com", "secret123", "patient")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        department = Department(name="Neurology", description="Brain care")
        db.add(department)
        db.commit()
        db.refresh(department)

        failed_service = Service(
            name="MRI",
            description="Brain imaging",
            department_id=department.id,
            status=ServiceStatus.PUBLISH_FAILED,
            is_published=False,
        )
        db.add(failed_service)
        db.commit()
        db.refresh(failed_service)
        service_id = failed_service.id
    finally:
        db.close()

    admin_token = _login(client, "admin@example.com", "secret123")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    admin_response = client.get("/api/v1/services?limit=20&offset=0", headers=admin_headers)
    assert admin_response.status_code == 200
    assert any(item["id"] == service_id and item["status"] == "PUBLISH_FAILED" for item in admin_response.json()["items"])

    patient_token = _login(client, "patient@example.com", "secret123")
    patient_headers = {"Authorization": f"Bearer {patient_token}"}
    public_response = client.get("/api/v1/public/services?limit=20&offset=0", headers=patient_headers)
    assert public_response.status_code == 200
    assert any(item["id"] == service_id and item["status"] == "PUBLISH_FAILED" for item in public_response.json()["items"])


def test_visit_illegal_transition_is_rejected(client):
    _create_user(client, "patient@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        patient_user = db.query(User).filter(User.email == "patient@example.com").one()
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()

        patient = _ensure_patient(db, patient_user.id)

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


def test_registration_saves_name_for_patient_accounts(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "namecheck@example.com",
            "password": "secret123",
            "role": "patient",
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "namecheck@example.com"

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "namecheck@example.com").one()
        assert user.patient is not None
        assert user.patient.first_name == "Ada"
        assert user.patient.last_name == "Lovelace"
    finally:
        db.close()


def test_admin_self_registration_is_blocked_by_default(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "admin-self@example.com",
            "password": "secret123",
            "role": "admin",
            "first_name": "Root",
            "last_name": "User",
        },
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["error"]["message"].lower()


def test_service_publish_starts_workflow_and_writes_chunks(client):
    _create_user_record("admin@example.com", "secret123", "admin")
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
        json={
            "name": "MRI Scan",
            "description": "MRI diagnostic",
            "preparation_instructions": "Bring prior imaging reports.",
            "department_id": department_id,
            "is_published": False,
        },
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
    assert status_payload["stage"] in {"EMBEDDING", "PERSISTING", "COMPLETE"}
    assert status_payload["chunks_total"] >= 1
    assert status_payload["embeddings_generated"] >= 1

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        service = db.query(Service).filter(Service.id == service_id).first()
        assert service is not None
        assert service.status == "PUBLISHED"
        assert service.is_published is True
        chunks = db.query(ContentChunk).filter(ContentChunk.service_id == service_id).all()
        assert len(chunks) >= 1
        assert chunks[0].embedding is not None
    finally:
        db.close()

    from app.core.settings import settings

    original_min_similarity = settings.retrieval_min_similarity
    settings.retrieval_min_similarity = 0.0
    try:
        search_response = client.post("/search", json={"query": "MRI Scan", "limit": 5}, headers=admin_headers)
        assert search_response.status_code == 200
        search_payload = search_response.json()
        assert search_payload["results"]
        result = next(item for item in search_payload["results"] if item["service_id"] == service_id)
        assert result["score"] > 0
        assert result["department"] == "Neurology"
        assert result["specialty"] is None
    finally:
        settings.retrieval_min_similarity = original_min_similarity
