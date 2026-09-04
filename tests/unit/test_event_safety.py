from app.workers.kafka import EventPublisher


def test_kafka_metadata_redacts_toplevel_denylist_keys():
    """Verify top-level denylist keys like 'password', 'secret' are removed."""
    safe = EventPublisher._validate_metadata({
        "appointment_id": 1,
        "password": "secret123",
        "secret_key": "hidden",
        "contact": {"email": "user@example.com"},
    })

    assert safe["appointment_id"] == 1
    assert "password" not in safe
    assert "secret_key" not in safe
    assert safe["contact"]["email"] == "user@example.com"


def test_kafka_metadata_preserves_safe_nested_ids():
    """Verify safe IDs are preserved in metadata."""
    safe = EventPublisher._validate_metadata({"data": {"patient_id": 2, "slot_id": 3}})

    assert safe == {"data": {"patient_id": 2, "slot_id": 3}}