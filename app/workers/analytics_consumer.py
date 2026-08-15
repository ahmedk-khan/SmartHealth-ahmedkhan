from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaConsumer
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.db import SessionLocal
from app.models import AnalyticsAppointmentDaily, AnalyticsProcessedEvent, AnalyticsServiceDaily

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
            consumer_timeout_ms=1000,
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
        lower_keys = {str(key).lower() for key in payload.keys()}
        return not lower_keys.intersection(forbidden)

    def _store_processed(self, db: Session, event_id: str, event_type: str, topic: str, payload: dict[str, Any]) -> None:
        existing = db.query(AnalyticsProcessedEvent).filter(AnalyticsProcessedEvent.event_id == event_id).first()
        if existing is not None:
            return

        db.add(
            AnalyticsProcessedEvent(
                event_id=event_id,
                event_type=event_type,
                topic=topic,
                payload=payload,
            )
        )

    def _update_appointment_metrics(self, db: Session, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("event_type", "unknown"))
        appointment_id = payload.get("appointment_id")
        patient_id = payload.get("patient_id")
        provider_id = payload.get("provider_id")
        service_id = payload.get("service_id")
        slot_id = payload.get("slot_id")
        status = payload.get("status")
        visit_status = payload.get("visit_status")
        event_date = datetime.now(timezone.utc).date().isoformat()

        if appointment_id is None:
            return

        record = (
            db.query(AnalyticsAppointmentDaily)
            .filter(
                AnalyticsAppointmentDaily.event_date == event_date,
                AnalyticsAppointmentDaily.event_type == event_type,
                AnalyticsAppointmentDaily.appointment_id == int(appointment_id),
            )
            .first()
        )

        if record is None:
            record = AnalyticsAppointmentDaily(
                event_date=event_date,
                event_type=event_type,
                appointment_id=int(appointment_id),
                patient_id=int(patient_id) if patient_id is not None else None,
                provider_id=int(provider_id) if provider_id is not None else None,
                service_id=int(service_id) if service_id is not None else None,
                slot_id=int(slot_id) if slot_id is not None else None,
                status=str(status) if status is not None else None,
                visit_status=str(visit_status) if visit_status is not None else None,
                total_events=0,
            )
            db.add(record)

        record.total_events += 1
        record.patient_id = int(patient_id) if patient_id is not None else record.patient_id
        record.provider_id = int(provider_id) if provider_id is not None else record.provider_id
        record.service_id = int(service_id) if service_id is not None else record.service_id
        record.slot_id = int(slot_id) if slot_id is not None else record.slot_id
        record.status = str(status) if status is not None else record.status
        record.visit_status = str(visit_status) if visit_status is not None else record.visit_status
        record.last_event_at = datetime.now(timezone.utc)
        record.updated_at = datetime.now(timezone.utc)

    def _update_service_metrics(self, db: Session, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("event_type", "unknown"))
        service_id = payload.get("service_id")
        department_id = payload.get("department_id")
        status = payload.get("status")
        event_date = datetime.now(timezone.utc).date().isoformat()

        if service_id is None:
            return

        record = (
            db.query(AnalyticsServiceDaily)
            .filter(
                AnalyticsServiceDaily.event_date == event_date,
                AnalyticsServiceDaily.event_type == event_type,
                AnalyticsServiceDaily.service_id == int(service_id),
            )
            .first()
        )

        if record is None:
            record = AnalyticsServiceDaily(
                event_date=event_date,
                event_type=event_type,
                service_id=int(service_id),
                department_id=int(department_id) if department_id is not None else None,
                status=str(status) if status is not None else None,
                total_events=0,
            )
            db.add(record)

        record.total_events += 1
        record.department_id = int(department_id) if department_id is not None else record.department_id
        record.status = str(status) if status is not None else record.status
        record.last_event_at = datetime.now(timezone.utc)
        record.updated_at = datetime.now(timezone.utc)

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
            processed = AnalyticsProcessedEvent(
                event_id=str(event_id),
                event_type=str(message.get("event_type", "unknown")),
                topic=topic,
                payload=message,
            )
            db.add(processed)
            try:
                db.flush()
            except Exception:
                db.rollback()
                return

            if "appointment" in topic:
                self._update_appointment_metrics(db, message)
            elif "service" in topic:
                self._update_service_metrics(db, message)
            db.commit()
        except Exception:
            db.rollback()
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
            except Exception as exc:  # pragma: no cover - runtime protection path
                logger.exception("Failed to process analytics event from topic %s", message.topic)
                continue


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    AnalyticsConsumer().run()
