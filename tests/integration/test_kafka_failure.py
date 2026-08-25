import pytest

from app.integrations.kafka_client import KafkaEventPublisher, KafkaProducerError
from app.services.healthcare_event_service import HealthcareEventService


@pytest.mark.integration
def test_kafka_broker_failure_is_converted_to_outbox(monkeypatch):
    """Requires Kafka disabled or unavailable and a configured test database."""
    publisher = KafkaEventPublisher()

    def fail(*args, **kwargs):
        raise KafkaProducerError("broker unavailable")

    monkeypatch.setattr(publisher, "publish_event", fail)
    result = HealthcareEventService(publisher).publish_appointment_event(
        "appointment.created",
        appointment_id=999999,
        patient_id=1,
    )

    assert result["status"] == "delivery_failed"