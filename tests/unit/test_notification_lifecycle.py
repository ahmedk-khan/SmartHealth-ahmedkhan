from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Appointment, AppointmentStatus, Department, Patient, Provider, Service, Slot, SlotStatus, User, UserRole
from app.services.notification_service import NotificationService


def test_notification_cancel_is_idempotent_and_sent_is_not_reversed():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        user = User(email="notify@example.com", hashed_password="hash", role=UserRole.patient)
        patient = Patient(user=user)
        department = Department(name="Notify")
        service = Service(name="Notify service", department=department)
        provider_user = User(email="provider-notify@example.com", hashed_password="hash", role=UserRole.provider)
        provider = Provider(user=provider_user)
        slot = Slot(provider=provider, service=service, status=SlotStatus.BOOKED, start_datetime=datetime(2026, 8, 30, 9, tzinfo=timezone.utc), end_datetime=datetime(2026, 8, 30, 10, tzinfo=timezone.utc))
        appointment = Appointment(patient=patient, provider=provider, service=service, slot=slot, status=AppointmentStatus.CONFIRMED)
        session.add(appointment)
        session.commit()

        notifications = NotificationService(session)
        pending = notifications.schedule_appointment_reminder(appointment.id)
        cancelled = notifications.cancel_notification(pending.id)
        assert cancelled.status.value == "CANCELLED"
        assert notifications.cancel_notification(pending.id).status.value == "CANCELLED"

        sent = notifications.send_appointment_reminder(appointment.id)
        assert sent["status"] == "cancelled"
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_visit_follow_up_lifecycle_and_list():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        user = User(email="followup@example.com", hashed_password="hash", role=UserRole.patient)
        patient = Patient(user=user)
        department = Department(name="Notify")
        service = Service(name="Notify service", department=department)
        provider_user = User(email="provider-notify@example.com", hashed_password="hash", role=UserRole.provider)
        provider = Provider(user=provider_user)
        slot = Slot(provider=provider, service=service, status=SlotStatus.BOOKED, start_datetime=datetime(2026, 8, 30, 9, tzinfo=timezone.utc), end_datetime=datetime(2026, 8, 30, 10, tzinfo=timezone.utc))
        appointment = Appointment(patient=patient, provider=provider, service=service, slot=slot, status=AppointmentStatus.CONFIRMED)
        session.add(appointment)
        session.commit()

        notifications = NotificationService(session)
        
        # Test creation of follow-up
        follow_up = notifications.create_follow_up(appointment)
        assert follow_up.type == "VISIT_FOLLOW_UP"
        assert follow_up.status.value == "PENDING"

        # Test listing notifications
        items, total = notifications.list_user_notifications(user.id, limit=10, offset=0)
        assert total == 1
        assert items[0].id == follow_up.id

        # Test sending follow-up
        result = notifications.send_visit_follow_up(appointment.id)
        assert result["status"] == "sent"

        # Test idempotency (already sent check)
        result_retry = notifications.send_visit_follow_up(appointment.id)
        assert result_retry["status"] == "already_sent"
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
