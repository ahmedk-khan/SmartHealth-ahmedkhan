import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import time


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
    AppointmentStatus,
    Appointment,
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
    WaitlistEntry,
    WaitlistStatus,
)
from app.repositories import AppointmentRepository
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


def test_five_concurrent_bookings_allow_only_one_confirmed_appointment(client):
    patient_emails = [f"concurrent-{index}@example.com" for index in range(5)]
    for email in patient_emails:
        _create_user(client, email, "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()
        provider = Provider(user_id=provider_user.id, bio="General medicine")
        department = Department(name="Concurrency", description="Concurrency test")
        db.add_all([provider, department])
        db.flush()
        service = Service(name="Concurrent checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.flush()
        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            status=SlotStatus.AVAILABLE,
            start_datetime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.commit()
        slot_id = slot.id
    finally:
        db.close()

    tokens = [_login(client, email, "secret123") for email in patient_emails]

    def book(token):
        return client.post(
            "/api/v1/appointments",
            json={"slot_id": slot_id},
            headers={"Authorization": f"Bearer {token}"},
        )

    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(book, tokens))

    assert sum(response.status_code == 202 for response in responses) == 1
    assert sum(response.status_code == 409 for response in responses) == 4
    confirmed = [response.json() for response in responses if response.status_code == 202]
    assert confirmed[0]["status"] == "CONFIRMED"
    winning_patient_id = confirmed[0]["patient_id"]

    db = SessionLocal()
    try:
        refreshed_slot = db.query(Slot).filter(Slot.id == slot_id).one()
        appointments = db.query(Appointment).filter(Appointment.slot_id == slot_id).all()
        assert refreshed_slot.status == SlotStatus.RESERVED
        assert len(appointments) == 1
        assert appointments[0].patient_id == winning_patient_id
        assert appointments[0].status == AppointmentStatus.CONFIRMED
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
    patient_checkin = client.post(f"/api/v1/appointments/{appointment.id}/visit/check-in", headers=patient_headers)
    assert patient_checkin.status_code == 403

    provider_token = _login(client, "provider@example.com", "secret123")
    provider_headers = {"Authorization": f"Bearer {provider_token}"}

    first_checkin = client.post(f"/api/v1/appointments/{appointment.id}/visit/check-in", headers=provider_headers)
    assert first_checkin.status_code == 200
    assert first_checkin.json()["visit_status"] == "CHECKED_IN"

    repeated_checkin = client.post(f"/api/v1/appointments/{appointment.id}/visit/check-in", headers=provider_headers)
    assert repeated_checkin.status_code == 200
    assert repeated_checkin.json()["visit_status"] == "CHECKED_IN"

    start = client.post(f"/api/v1/appointments/{appointment.id}/visit/start", headers=provider_headers)
    assert start.status_code == 200
    assert start.json()["visit_status"] == "IN_PROGRESS"

    complete = client.post(f"/api/v1/appointments/{appointment.id}/visit/complete", headers=provider_headers)
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
    assert not any(item["id"] == service_id for item in public_response.json()["items"])


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
    assert response.status_code == 403


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


def test_service_publish_starts_workflow_and_writes_chunks(client, monkeypatch):
    async def temporal_unavailable(*args, **kwargs):
        raise ConnectionError("Temporal unavailable in unit test")

    from app.services import service_management

    monkeypatch.setattr(service_management.temporal_client.Client, "connect", temporal_unavailable)

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

    deadline = time.monotonic() + 10
    status_payload = None
    while time.monotonic() < deadline:
        status_response = client.get(f"/api/v1/services/{service_id}/publish-status", headers=admin_headers)
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload.get("status") == "PUBLISHED":
            break
        time.sleep(0.1)

    assert status_payload is not None
    assert status_payload["workflow_id"] == f"service-publish-{service_id}"
    assert status_payload["status"] == "PUBLISHED"
    assert status_payload["stage"] == "COMPLETE"
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


def test_cancelling_appointment_promotes_oldest_waitlisted_patient(client):
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        provider_user = User(email="provider@example.com", hashed_password="hash", role=UserRole.provider)
        cancelled_patient_user = User(email="cancelled@example.com", hashed_password="hash", role=UserRole.patient)
        waiting_patient_user = User(email="waiting@example.com", hashed_password="hash", role=UserRole.patient)
        db.add_all([provider_user, cancelled_patient_user, waiting_patient_user])
        db.flush()

        provider = Provider(user_id=provider_user.id, bio="General medicine")
        cancelled_patient = Patient(user_id=cancelled_patient_user.id)
        waiting_patient = Patient(user_id=waiting_patient_user.id)
        department = Department(name="Cardiology", description="Heart care")
        db.add_all([provider, cancelled_patient, waiting_patient, department])
        db.flush()

        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.flush()

        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            patient_id=cancelled_patient.id,
            status=SlotStatus.BOOKED,
            start_datetime=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 2, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.flush()

        appointment = Appointment(
            patient_id=cancelled_patient.id,
            provider_id=provider.id,
            service_id=service.id,
            slot_id=slot.id,
            status=AppointmentStatus.CONFIRMED,
        )
        db.add(appointment)
        db.flush()
        waitlist_entry = WaitlistEntry(slot_id=slot.id, patient_id=waiting_patient.id, status=WaitlistStatus.WAITING)
        db.add(waitlist_entry)
        db.commit()

        cancelled = AppointmentRepository(db).cancel(appointment)

        promoted = db.query(Appointment).filter(
            Appointment.slot_id == slot.id,
            Appointment.patient_id == waiting_patient.id,
        ).one()
        refreshed_slot = db.query(Slot).filter(Slot.id == slot.id).one()
        refreshed_entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_entry.id).one()
        assert cancelled.status == AppointmentStatus.CANCELLED
        assert refreshed_slot.status == SlotStatus.RESERVED
        assert refreshed_slot.patient_id == waiting_patient.id
        assert refreshed_entry.status == WaitlistStatus.PROMOTED
        assert promoted.status == AppointmentStatus.CONFIRMED
    finally:
        db.close()


def test_cancel_api_books_oldest_waitlisted_patient_and_lists_appointment(client):
    _create_user(client, "cancelled@example.com", "secret123", "patient")
    _create_user(client, "first-waiting@example.com", "secret123", "patient")
    _create_user(client, "second-waiting@example.com", "secret123", "patient")
    _create_user(client, "provider@example.com", "secret123", "provider")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        cancelled_user = db.query(User).filter(User.email == "cancelled@example.com").one()
        first_user = db.query(User).filter(User.email == "first-waiting@example.com").one()
        second_user = db.query(User).filter(User.email == "second-waiting@example.com").one()
        provider_user = db.query(User).filter(User.email == "provider@example.com").one()
        cancelled_patient = db.query(Patient).filter(Patient.user_id == cancelled_user.id).one()
        first_patient = db.query(Patient).filter(Patient.user_id == first_user.id).one()
        second_patient = db.query(Patient).filter(Patient.user_id == second_user.id).one()
        provider = Provider(user_id=provider_user.id, bio="General medicine")
        department = Department(name="Cardiology", description="Heart care")
        db.add_all([provider, department])
        db.flush()
        service = Service(name="Checkup", department_id=department.id, is_published=True)
        db.add(service)
        db.flush()
        slot = Slot(
            provider_id=provider.id,
            service_id=service.id,
            patient_id=cancelled_patient.id,
            status=SlotStatus.BOOKED,
            start_datetime=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 8, 2, 9, 30, tzinfo=timezone.utc),
        )
        db.add(slot)
        db.flush()
        appointment = Appointment(
            patient_id=cancelled_patient.id,
            provider_id=provider.id,
            service_id=service.id,
            slot_id=slot.id,
            status=AppointmentStatus.CONFIRMED,
        )
        db.add(appointment)
        db.flush()
        base_time = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        first_entry = WaitlistEntry(
            slot_id=slot.id,
            patient_id=first_patient.id,
            status=WaitlistStatus.WAITING,
            created_at=base_time,
        )
        second_entry = WaitlistEntry(
            slot_id=slot.id,
            patient_id=second_patient.id,
            status=WaitlistStatus.WAITING,
            created_at=base_time.replace(second=1),
        )
        db.add_all([first_entry, second_entry])
        db.commit()
        appointment_id = appointment.id
        slot_id = slot.id
        first_patient_id = first_patient.id
        second_patient_id = second_patient.id
    finally:
        db.close()

    cancelled_token = _login(client, "cancelled@example.com", "secret123")
    cancel_response = client.post(
        f"/api/v1/appointments/{appointment_id}/cancel",
        headers={"Authorization": f"Bearer {cancelled_token}"},
    )
    assert cancel_response.status_code == 200

    first_token = _login(client, "first-waiting@example.com", "secret123")
    list_response = client.get(
        "/api/v1/appointments",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["slot_id"] == slot_id
    assert items[0]["status"] == "CONFIRMED"

    db = SessionLocal()
    try:
        promoted_entry = db.query(WaitlistEntry).filter(WaitlistEntry.patient_id == first_patient_id).one()
        waiting_entry = db.query(WaitlistEntry).filter(WaitlistEntry.patient_id == second_patient_id).one()
        refreshed_slot = db.query(Slot).filter(Slot.id == slot_id).one()
        assert promoted_entry.status == WaitlistStatus.PROMOTED
        assert waiting_entry.status == WaitlistStatus.WAITING
        assert refreshed_slot.patient_id == first_patient_id
        assert refreshed_slot.status == SlotStatus.RESERVED
    finally:
        db.close()
