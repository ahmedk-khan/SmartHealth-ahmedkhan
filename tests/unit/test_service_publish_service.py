"""Unit tests for service publish service and Kafka consumer DLQ behavior."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.models import ServiceStatus
from app.services.service_publish_service import ServicePublishService
from app.workers.kafka.consumer import AnalyticsConsumer, ConsumerConfigError


def test_validate_for_publication_rejects_missing_service():
    db = MagicMock()
    service = ServicePublishService(db)
    service.services.get_for_publication = MagicMock(return_value=None)

    with pytest.raises(NotFoundError, match="Service not found"):
        service.validate_for_publication(1)


def test_validate_for_publication_marks_incomplete_service_failed():
    db = MagicMock()
    publish_service = ServicePublishService(db)
    mock_repo = MagicMock()
    publish_service.services = mock_repo
    incomplete = SimpleNamespace(
        id=1,
        status=ServiceStatus.DRAFT,
        description="",
        preparation_instructions="prep",
        department=SimpleNamespace(name="Cardiology"),
    )
    mock_repo.get_for_publication.return_value = incomplete

    with pytest.raises(ValidationError, match="Service is incomplete"):
        publish_service.validate_for_publication(1)

    mock_repo.mark_publish_failed.assert_called_once_with(incomplete)


def test_validate_for_publication_returns_publishing_payload():
    db = MagicMock()
    publish_service = ServicePublishService(db)
    mock_repo = MagicMock()
    publish_service.services = mock_repo
    record = SimpleNamespace(
        id=3,
        status=ServiceStatus.DRAFT,
        name="MRI",
        description="Brain scan",
        specialty="Neurology",
        preparation_instructions="Fast for 6 hours",
        department_id=2,
        department=SimpleNamespace(name="Radiology"),
    )
    mock_repo.get_for_publication.return_value = record

    result = publish_service.validate_for_publication(3)

    assert result["status"] == ServiceStatus.PUBLISHING.value
    assert result["service"]["id"] == 3
    assert result["service"]["department_name"] == "Radiology"
    mock_repo.mark_publishing.assert_called_once_with(record)


def test_chunk_service_splits_description_into_chunks():
    service_struct = {
        "service_id": 1,
        "title": "MRI",
        "description": "A" * 250,
        "department_name": "Radiology",
        "specialty": "Neuro",
        "preparation_instructions": "Fast",
    }

    chunks = ServicePublishService.chunk_service(service_struct)

    assert len(chunks) == 3
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["service_id"] == 1
    assert "content_hash" in chunks[0]


def test_mark_failed_updates_service_when_present():
    db = MagicMock()
    publish_service = ServicePublishService(db)
    mock_repo = MagicMock()
    publish_service.services = mock_repo
    record = SimpleNamespace(id=9)
    mock_repo.get_for_publication.return_value = record

    result = publish_service.mark_failed(9)

    assert result == {"service_id": 9, "failed": True}
    mock_repo.mark_publish_failed.assert_called_once_with(record)


def test_consumer_retries_before_dlq():
    consumer = AnalyticsConsumer()
    consumer.max_retries = 3
    consumer._consumer = MagicMock()
    message = SimpleNamespace(topic="app.appointment.created", partition=0, offset=42, value={"event_id": "evt-1"})

    with patch.object(consumer, "_publish_to_dlq") as mock_dlq:
        consumer._handle_processing_failure(message, RuntimeError("boom"))
        consumer._handle_processing_failure(message, RuntimeError("boom"))
        consumer._handle_processing_failure(message, RuntimeError("boom"))

    mock_dlq.assert_called_once()
    consumer._consumer.commit.assert_called_once()


def test_consumer_publishes_dlq_payload(monkeypatch):
    consumer = AnalyticsConsumer()
    producer = MagicMock()
    monkeypatch.setattr("app.workers.kafka.consumer.settings.kafka_enabled", True)
    monkeypatch.setattr("app.workers.kafka.consumer.get_kafka_client", lambda: SimpleNamespace(get_producer=lambda: producer))

    message = SimpleNamespace(topic="app.appointment.created", partition=1, offset=7, value={"event_id": "evt-2"})
    consumer._failure_counts[(message.topic, message.partition, message.offset)] = 3

    consumer._publish_to_dlq(message, message.value, ValueError("bad data"))

    producer.send.assert_called_once()
    args, kwargs = producer.send.call_args
    assert args[0] == "app.dlq"
    payload = json.loads(kwargs["value"].decode("utf-8"))
    assert payload["original_topic"] == "app.appointment.created"
    assert payload["error_type"] == "ValueError"
    assert payload["payload"]["event_id"] == "evt-2"
    producer.flush.assert_called_once()


def test_consumer_rejects_unsafe_payload():
    consumer = AnalyticsConsumer()
    payload = {"event_id": "evt-3", "notes": "private diagnosis"}

    with pytest.raises(ConsumerConfigError, match="forbidden PHI fields"):
        consumer.process_message(payload, "app.appointment.created")
