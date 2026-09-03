"""Kafka analytics consumer implementation."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.core.metrics import record_event_consumed, record_event_failed
from app.repositories import AnalyticsRepository
from app.workers.kafka.client import get_kafka_client
from app.workers.kafka.config import kafka_config

logger = logging.getLogger(__name__)

# Startup can race Kafka readiness even when compose marks the broker healthy.
_CONNECT_ATTEMPTS = 30
_CONNECT_BASE_DELAY_SECONDS = 2
_CONNECT_MAX_DELAY_SECONDS = 30


class ConsumerConfigError(RuntimeError):
    pass


class AnalyticsConsumer:
    def __init__(self) -> None:
        self.bootstrap_servers = settings.kafka_bootstrap_servers
        self.consumer_group = settings.kafka_consumer_group
        self.topic_prefix = settings.kafka_topic_prefix
        self.max_retries = settings.kafka_consumer_max_retries
        self._consumer: KafkaConsumer | None = None
        self._failure_counts: dict[tuple[str, int, int], int] = {}

    def _bootstrap_server_list(self) -> list[str]:
        return [server.strip() for server in self.bootstrap_servers.split(",") if server.strip()]

    def _create_consumer(self) -> KafkaConsumer:
        """Create a Kafka consumer, retrying while brokers are still starting."""
        servers = self._bootstrap_server_list()
        last_error: Exception | None = None

        for attempt in range(1, _CONNECT_ATTEMPTS + 1):
            try:
                return KafkaConsumer(
                    bootstrap_servers=servers,
                    auto_offset_reset="earliest",
                    enable_auto_commit=False,
                    group_id=self.consumer_group,
                    value_deserializer=lambda value: json.loads(value.decode("utf-8")),
                    api_version_auto_timeout_ms=10000,
                    request_timeout_ms=30000,
                )
            except NoBrokersAvailable as exc:
                last_error = exc
                delay = min(
                    _CONNECT_BASE_DELAY_SECONDS * (2 ** min(attempt - 1, 4)),
                    _CONNECT_MAX_DELAY_SECONDS,
                )
                logger.warning(
                    "Kafka brokers unavailable at %s (attempt %s/%s); retrying in %ss",
                    servers,
                    attempt,
                    _CONNECT_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)

        raise ConsumerConfigError(
            f"Kafka brokers unavailable after {_CONNECT_ATTEMPTS} attempts: {servers}"
        ) from last_error

    @property
    def consumer(self) -> KafkaConsumer:
        if self._consumer is not None:
            return self._consumer

        self._consumer = self._create_consumer()
        return self._consumer

    def _topics(self) -> list[str]:
        return [
            f"{self.topic_prefix}.appointment.created",
            f"{self.topic_prefix}.appointment.cancelled",
            f"{self.topic_prefix}.appointment.rescheduled",
            f"{self.topic_prefix}.appointment.visit_status_changed",
            f"{self.topic_prefix}.service.published",
        ]

    def _message_key(self, message: Any) -> tuple[str, int, int]:
        return (message.topic, message.partition, message.offset)

    def _is_safe_payload(self, payload: dict[str, Any]) -> bool:
        forbidden = {"name", "email", "phone", "dob", "address", "diagnosis", "notes", "symptoms", "medical_history"}

        def contains_forbidden(value: Any) -> bool:
            if isinstance(value, dict):
                return any(str(key).lower() in forbidden or contains_forbidden(item) for key, item in value.items())
            if isinstance(value, list):
                return any(contains_forbidden(item) for item in value)
            return False

        return not contains_forbidden(payload)

    def _update_appointment_metrics(self, db: Session, payload: dict[str, Any]) -> None:
        AnalyticsRepository(db).update_appointment_metrics(payload)

    def _update_service_metrics(self, db: Session, payload: dict[str, Any]) -> None:
        AnalyticsRepository(db).update_service_metrics(payload)

    def _publish_to_dlq(self, message: Any, payload: dict[str, Any], error: Exception) -> None:
        if not settings.kafka_enabled:
            logger.warning("Kafka disabled; failed message not sent to DLQ", extra={"topic": message.topic})
            return

        producer = get_kafka_client().get_producer()
        if producer is None:
            logger.error("Kafka producer unavailable; failed message not sent to DLQ", extra={"topic": message.topic})
            return

        dlq_payload = {
            "event_id": str(uuid4()),
            "event_type": "analytics.consumer.dlq",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": "smarthealth-analytics-consumer",
            "original_topic": message.topic,
            "original_partition": message.partition,
            "original_offset": message.offset,
            "failure_count": self._failure_counts.get(self._message_key(message), 0),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "payload": payload,
        }
        producer.send(
            kafka_config.dlq_topic(),
            key=f"{message.topic}:{message.partition}:{message.offset}".encode("utf-8"),
            value=json.dumps(dlq_payload).encode("utf-8"),
        )
        producer.flush()
        logger.error(
            "Analytics event moved to DLQ",
            extra={
                "topic": message.topic,
                "partition": message.partition,
                "offset": message.offset,
                "dlq_topic": kafka_config.dlq_topic(),
            },
        )

    def process_message(self, message: dict[str, Any], topic: str) -> None:
        if not isinstance(message, dict):
            raise ConsumerConfigError("Kafka payload must be a JSON object")
        if not self._is_safe_payload(message):
            raise ConsumerConfigError("Kafka payload contains forbidden PHI fields")

        event_id = message.get("event_id")
        if not event_id:
            raise ConsumerConfigError("Kafka payload missing event_id")

        from app import db as db_module

        db = db_module.SessionLocal()
        try:
            repository = AnalyticsRepository(db)
            try:
                repository.stage_processed_event(
                    str(event_id),
                    str(message.get("event_type", "unknown")),
                    topic,
                    message,
                )
            except Exception:
                repository.rollback()
                return

            if "appointment" in topic:
                self._update_appointment_metrics(db, message)
            elif "service" in topic:
                self._update_service_metrics(db, message)
            repository.commit()
            record_event_consumed(topic)
        except Exception as exc:
            record_event_failed(topic, type(exc).__name__)
            AnalyticsRepository(db).rollback()
            raise
        finally:
            db.close()

    def _handle_processing_failure(self, message: Any, exc: Exception) -> None:
        key = self._message_key(message)
        attempts = self._failure_counts.get(key, 0) + 1
        self._failure_counts[key] = attempts

        if attempts < self.max_retries:
            logger.warning(
                "Failed to process analytics event; will retry",
                extra={
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                    "attempt": attempts,
                    "max_retries": self.max_retries,
                },
            )
            return

        payload = message.value if isinstance(message.value, dict) else {}
        try:
            self._publish_to_dlq(message, payload, exc)
        except Exception:
            logger.exception(
                "Failed to publish analytics event to DLQ",
                extra={"topic": message.topic, "partition": message.partition, "offset": message.offset},
            )
            return

        self._failure_counts.pop(key, None)
        self.consumer.commit()
        logger.info(
            "Committed offset after DLQ publish",
            extra={"topic": message.topic, "partition": message.partition, "offset": message.offset},
        )

    def run(self) -> None:
        if not settings.kafka_enabled:
            logger.info("Kafka analytics consumer is disabled via settings")
            return

        self.consumer.subscribe(self._topics())
        logger.info("Analytics consumer started for topics: %s", self._topics())

        for message in self.consumer:
            try:
                payload = message.value
                if payload is None:
                    self.consumer.commit()
                    continue
                self.process_message(payload, message.topic)
                self._failure_counts.pop(self._message_key(message), None)
                self.consumer.commit()
            except Exception as exc:
                logger.exception("Failed to process analytics event from topic %s", message.topic)
                self._handle_processing_failure(message, exc)


__all__ = ["AnalyticsConsumer", "ConsumerConfigError"]
