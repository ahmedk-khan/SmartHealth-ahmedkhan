"""Kafka analytics consumer implementation."""

from __future__ import annotations

import json
import logging
from typing import Any

from kafka import KafkaConsumer
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.db import SessionLocal
from app.repositories import AnalyticsRepository

logger = logging.getLogger(__name__)


class ConsumerConfigError(RuntimeError):
    pass


class AnalyticsConsumer:
    def __init__(self) -> None:
        self.bootstrap_servers = settings.kafka_bootstrap_servers
        self.consumer_group = settings.kafka_consumer_group
        self.topic_prefix = settings.kafka_topic_prefix
        self._consumer: KafkaConsumer | None = None

    @property
    def consumer(self) -> KafkaConsumer:
        if self._consumer is not None:
            return self._consumer

        self._consumer = KafkaConsumer(
            bootstrap_servers=self.bootstrap_servers,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id=self.consumer_group,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )
        return self._consumer

    def _topics(self) -> list[str]:
        return [
            f"{self.topic_prefix}.appointment.created",
            f"{self.topic_prefix}.appointment.cancelled",
            f"{self.topic_prefix}.appointment.rescheduled",
            f"{self.topic_prefix}.appointment.visit_status_changed",
            f"{self.topic_prefix}.service.published",
        ]

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

    def process_message(self, message: dict[str, Any], topic: str) -> None:
        if not isinstance(message, dict):
            raise ConsumerConfigError("Kafka payload must be a JSON object")
        if not self._is_safe_payload(message):
            raise ConsumerConfigError("Kafka payload contains forbidden PHI fields")

        event_id = message.get("event_id")
        if not event_id:
            raise ConsumerConfigError("Kafka payload missing event_id")

        db = SessionLocal()
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
        except Exception:
            AnalyticsRepository(db).rollback()
            raise
        finally:
            db.close()

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
                    continue
                self.process_message(payload, message.topic)
                self.consumer.commit()
            except Exception:
                logger.exception("Failed to process analytics event from topic %s", message.topic)
                continue


__all__ = ["AnalyticsConsumer", "ConsumerConfigError"]
