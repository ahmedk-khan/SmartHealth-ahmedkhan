from app.integrations.kafka_client import KafkaEventPublisher


def test_kafka_metadata_redacts_nested_phi_keys():
    safe = KafkaEventPublisher._validate_metadata({
        "appointment_id": 1,
        "data": {"patient_id": 2, "contact": {"email": "secret@example.com"}},
    })

    assert safe["appointment_id"] == 1
    assert "email" not in safe["data"]["contact"]


def test_kafka_metadata_preserves_safe_nested_ids():
    safe = KafkaEventPublisher._validate_metadata({"data": {"patient_id": 2, "slot_id": 3}})

    assert safe == {"data": {"patient_id": 2, "slot_id": 3}}