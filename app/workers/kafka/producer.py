"""Kafka producer implementation."""

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.core.logging import get_correlation_id, get_request_id
from app.workers.kafka.client import get_kafka_client
from app.workers.kafka.config import kafka_config
from app.workers.kafka.exceptions import KafkaPublisherError, KafkaSerializationError

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
    "data",
    "scheduled_at",
    "checked_in_at",
    "wait_seconds",
}

_DENYLIST_KEYS = {
    "password",
    "secret",
    "token",
    "key",
    "ssn",
    "pii",
    "phi",
    "medical_record",
}


class EventPublisher:
    """Kafka event publisher with PHI-safe serialization."""

    def __init__(self, client=None):
        self.client = client or get_kafka_client()
        self.config = kafka_config
        self._enabled = self.config.enabled

    async def publish(
        self,
        topic: str,
        key: str,
        value: dict[str, Any],
        headers: Optional[dict[str, str]] = None,
    ) -> str:
        if not self._enabled:
            logger.warning(f"Kafka disabled; event not published to {topic}")
            return ""

        try:
            sanitized_value = self._sanitize_event(value)
            event_id = value.get("event_id") or str(uuid4())
            sanitized_value.setdefault("event_id", event_id)
            sanitized_value.setdefault("occurred_at", datetime.now(timezone.utc).isoformat())
            sanitized_value.setdefault("correlation_id", get_correlation_id())
            sanitized_value.setdefault("request_id", get_request_id())
            serialized = json.dumps(sanitized_value)

            producer = self.client.get_producer()
            if producer is None:
                logger.warning(f"Kafka producer unavailable; event {event_id} queued for retry")
                return event_id

            loop = asyncio.get_event_loop()
            future = await loop.run_in_executor(
                None,
                self._send_to_kafka,
                producer,
                topic,
                key,
                serialized,
            )

            logger.info(
                "Event published",
                extra={
                    "event_id": event_id,
                    "event_type": value.get("event_type"),
                    "topic": topic,
                    "partition": future.partition if future else None,
                },
            )
            return event_id
        except json.JSONDecodeError as e:
            raise KafkaSerializationError(f"Failed to serialize event: {e}") from e
        except Exception as e:
            raise KafkaPublisherError(f"Failed to publish event to {topic}: {e}") from e

    def publish_event(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str | int,
        **metadata: Any,
    ) -> dict[str, Any]:
        """Synchronously publish an event to Kafka for callers that are not async."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.publish_event_async(event_type, entity_type, entity_id, **metadata))

        raise RuntimeError(
            "EventPublisher.publish_event() cannot be called from a running event loop; "
            "use publish_event_async() instead."
        )

    async def publish_event_async(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str | int,
        **metadata: Any,
    ) -> dict[str, Any]:
        topic = self.config.topic(event_type)
        key = f"{entity_type}:{entity_id}"
        event_payload = {
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            **metadata,
        }
        event_id = await self.publish(topic, key, event_payload)
        event_payload["event_id"] = event_id
        return event_payload

    async def health_check(self) -> bool:
        if not self._enabled:
            return True
        return self.client.is_healthy()

    @staticmethod
    def _validate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            key_lower = normalized_key.lower()
            if any(denied in key_lower for denied in _DENYLIST_KEYS):
                logger.warning(f"Removed denylist field from metadata: {key}")
                continue
            sanitized[normalized_key] = value
        return sanitized

    @staticmethod
    def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
        sanitized = {}
        for key, value in event.items():
            key_lower = key.lower()
            if any(denied in key_lower for denied in _DENYLIST_KEYS):
                logger.warning(f"Removed denylist field from event: {key}")
                continue
            if key in _ALLOWED_EVENT_KEYS or isinstance(value, (dict, list)):
                sanitized[key] = value
            else:
                logger.debug(f"Skipped non-allowlist field: {key}")
        return sanitized

    @staticmethod
    def _send_to_kafka(producer: Any, topic: str, key: str, value: str) -> Any:
        future = producer.send(topic, key=key.encode("utf-8"), value=value)
        return future.get(timeout=10)


class KafkaProducer:
    """Backward-compatible wrapper around EventPublisher."""

    def __init__(self, publisher: EventPublisher | None = None) -> None:
        self.publisher = publisher or EventPublisher()

    async def publish(self, event_type: str, entity_type: str, entity_id: str | int, **metadata: Any) -> dict[str, Any]:
        return await self.publisher.publish_event_async(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            **metadata,
        )


__all__ = ["EventPublisher", "KafkaProducer"]
