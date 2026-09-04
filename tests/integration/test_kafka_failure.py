import pytest

from app.db import SessionLocal
from app.services.healthcare_event_service import HealthcareEventService
from app.workers.kafka import EventPublisher
from app.workers.kafka.exceptions import KafkaPublisherError


@pytest.mark.integration
def test_kafka_broker_failure_is_converted_to_outbox(monkeypatch):
    """Requires Kafka disabled or unavailable and a configured test database."""
    publisher = EventPublisher()

    def fail(*args, **kwargs):
        raise KafkaPublisherError("broker unavailable")

    monkeypatch.setattr(publisher, "publish_event_async", fail)
    db = SessionLocal()
    try:
        result = HealthcareEventService(db, publisher).publish_appointment_event(
            "appointment.created",
            appointment_id=999999,
            patient_id=1,
        )
    finally:
        db.close()

    assert result["status"] == "delivery_failed"