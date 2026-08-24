from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kafka import KafkaProducer

from app.core.exceptions import AppError
from app.core.settings import settings

logger = logging.getLogger(__name__)

_ALLOWED_EVENT_KEYS = {
    "event_id",
    "event_type",
    "occurred_at",
    "source",
    "schema_version",
    "entity_type",
    "entity_id",
    "correlation_id",
    "request_id",
    "appointment_id",
    "patient_id",
    "provider_id",
    "service_id",
    "slot_id",
    "old_slot_id",
    "new_slot_id",
    "department_id",
    "billing_id",
    "amount",
    "visit_status",
    "status",
    "workflow_id",
    "version",
}

_DENYLIST_KEYS = {
    "name",
    "email",
    "phone",
    "mobile",
    "dob",
    "date_of_birth",
    "address",
    "street",
    "city",
    "postal_code",
    "ssn",
    "diagnosis",
    "symptoms",
    "notes",
    "medical_history",
    "insurance",
    "allergies",
}


class KafkaProducerError(AppError):
    def __init__(self, message: str, detail: Any = None):
        super().__init__(message=message, status_code=503, error_type="kafka_publish_error", detail=detail)


class KafkaEventPublisher:
    def __init__(self) -> None:
        self.enabled = settings.kafka_enabled
        self.bootstrap_servers = settings.kafka_bootstrap_servers
        self.topic_prefix = settings.kafka_topic_prefix
        self._producer: KafkaProducer | None = None

    def _get_producer(self) -> KafkaProducer | None:
        if not self.enabled:
            return None

        if self._producer is not None:
            return self._producer

        try:
            self._producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda value: json.dumps(value, default=str).encode("utf-8"),
                key_serializer=lambda key: key.encode("utf-8") if isinstance(key, str) else key,
                acks="all",
                retries=3,
                retry_backoff_ms=250,
            )
            return self._producer
        except Exception as exc:  # pragma: no cover - environment error path
            logger.exception("Kafka producer initialization failed")
            raise KafkaProducerError("Kafka producer could not be initialized", detail=str(exc)) from exc

    @staticmethod
    def _build_topic_name(event_type: str, topic_prefix: str) -> str:
        normalized = event_type.strip().lower().replace(" ", ".")
        return f"{topic_prefix}.{normalized}" if topic_prefix else normalized

    @staticmethod
    def _validate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        safe_payload: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            normalized_key = str(key).strip()
            if not normalized_key or normalized_key.lower() in _DENYLIST_KEYS:
                continue
            if normalized_key.lower() not in _ALLOWED_EVENT_KEYS:
                continue
            safe_payload[normalized_key] = value
        return safe_payload

    def publish_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str | int,
        **metadata: Any,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "status": "disabled",
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
            }

        if not event_type or not entity_type or entity_id is None:
            raise KafkaProducerError("Kafka event requires an event type, entity type, and entity id")

        normalized_metadata = self._validate_metadata(metadata)
        payload: dict[str, Any] = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "smarthealth-api",
            "schema_version": 1,
            "version": 1,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            **normalized_metadata,
        }
        payload["data"] = dict(normalized_metadata)

        producer = self._get_producer()
        if producer is None:
            raise KafkaProducerError("Kafka producer is disabled or unavailable")

        topic_name = self._build_topic_name(event_type, self.topic_prefix)
        try:
            future = producer.send(topic_name, value=payload)
            producer.flush(timeout=10)
            metadata_record = future.get(timeout=10)
        except Exception as exc:  # pragma: no cover - broker/network error path
            logger.exception("Failed to publish Kafka event %s to %s", event_type, topic_name)
            raise KafkaProducerError("Failed to publish healthcare event to Kafka", detail=str(exc)) from exc

        return {
            "status": "published",
            "topic": topic_name,
            "partition": metadata_record.partition if metadata_record else None,
            "offset": metadata_record.offset if metadata_record else None,
            "event_id": payload["event_id"],
        }
