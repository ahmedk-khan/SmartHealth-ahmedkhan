from __future__ import annotations

import logging
from uuid import uuid4
from sqlalchemy.orm import Session
from app.integrations.kafka_client import KafkaEventPublisher, KafkaProducerError
from app.core.logging import get_correlation_id, get_request_id
from app.repositories.outbox import OutboxRepository
from app.models.outbox import OutboxEvent


logger = logging.getLogger(__name__)


class HealthcareEventService:
    """
    Service for publishing healthcare domain events.
    
    Automatically includes correlation ID and request ID from context in all events,
    ensuring end-to-end traceability across the system.
    """
    
    def __init__(self, db: Session, publisher: KafkaEventPublisher | None = None) -> None:
        self.outbox = OutboxRepository(db)
        self.publisher = publisher or KafkaEventPublisher()

    def _save_outbox(self, event_type: str, entity_type: str, entity_id: int, payload: dict[str, object], error: str) -> None:
        try:
            event = OutboxEvent(
                    event_id=str(payload.get("event_id") or uuid4()),
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    payload=payload,
                    correlation_id=str(payload.get("correlation_id")) if payload.get("correlation_id") else None,
                    last_error=error,
                )
            self.outbox.add(event)
            self.outbox.commit()
        except Exception:
            logger.exception("Failed to persist event to outbox", extra={"event_type": event_type, "entity_id": entity_id})

    def publish_appointment_event(
        self,
        event_type: str,
        *,
        appointment_id: int,
        patient_id: int | None = None,
        provider_id: int | None = None,
        service_id: int | None = None,
        slot_id: int | None = None,
        old_slot_id: int | None = None,
        new_slot_id: int | None = None,
        department_id: int | None = None,
        status: str | None = None,
        visit_status: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        workflow_id: str | None = None,
        scheduled_at: str | None = None,
        checked_in_at: str | None = None,
        wait_seconds: int | None = None,
    ) -> dict[str, object]:
        """
        Publish an appointment event with automatic correlation context.
        
        Args:
            event_type: Type of event (e.g., 'appointment.created', 'appointment.cancelled')
            appointment_id: ID of the appointment
            patient_id: ID of the patient (optional)
            provider_id: ID of the provider (optional)
            service_id: ID of the service (optional)
            slot_id: ID of the slot (optional)
            old_slot_id: Previous slot ID if slot changed (optional)
            new_slot_id: New slot ID if slot changed (optional)
            department_id: ID of the department (optional)
            status: Appointment status (optional)
            visit_status: Visit status (optional)
            request_id: HTTP request ID (auto-captured if not provided)
            correlation_id: Correlation ID (auto-captured if not provided)
            workflow_id: Temporal workflow ID (optional)
        
        Returns:
            Dictionary containing event publication result
        """
        # Auto-capture from context if not explicitly provided
        resolved_correlation_id = correlation_id or get_correlation_id()
        resolved_request_id = request_id or get_request_id()
        event_id = str(uuid4())
        
        metadata = {
            "appointment_id": appointment_id,
            "patient_id": patient_id,
            "provider_id": provider_id,
            "service_id": service_id,
            "slot_id": slot_id,
            "old_slot_id": old_slot_id,
            "new_slot_id": new_slot_id,
            "department_id": department_id,
            "status": status,
            "visit_status": visit_status,
            "request_id": resolved_request_id,
            "correlation_id": resolved_correlation_id,
            "workflow_id": workflow_id,
            "event_id": event_id,
            "scheduled_at": scheduled_at,
            "checked_in_at": checked_in_at,
            "wait_seconds": wait_seconds,
        }
        
        try:
            result = self.publisher.publish_event(
                event_type=event_type,
                entity_type="appointment",
                entity_id=appointment_id,
                **metadata,
            )
        except KafkaProducerError as exc:
            logger.error("Appointment event delivery failed after commit: %s", exc, extra={"event_type": event_type, "appointment_id": appointment_id})
            self._save_outbox(event_type, "appointment", appointment_id, metadata, str(exc))
            return {"status": "delivery_failed", "event_type": event_type, "entity_id": str(appointment_id)}
        
        logger.info(
            f"Appointment event published: {event_type}",
            extra={
                "event_type": event_type,
                "entity_type": "appointment",
                "appointment_id": appointment_id,
                "correlation_id": resolved_correlation_id,
                "request_id": resolved_request_id,
            }
        )
        
        return result

    def publish_service_event(
        self,
        event_type: str,
        *,
        service_id: int,
        department_id: int | None = None,
        status: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        """
        Publish a service event with automatic correlation context.
        
        Args:
            event_type: Type of event (e.g., 'service.published', 'service.updated')
            service_id: ID of the service
            department_id: ID of the department (optional)
            status: Service status (optional)
            request_id: HTTP request ID (auto-captured if not provided)
            correlation_id: Correlation ID (auto-captured if not provided)
        
        Returns:
            Dictionary containing event publication result
        """
        # Auto-capture from context if not explicitly provided
        resolved_correlation_id = correlation_id or get_correlation_id()
        resolved_request_id = request_id or get_request_id()
        
        metadata = {
            "service_id": service_id,
            "department_id": department_id,
            "status": status,
            "request_id": resolved_request_id,
            "correlation_id": resolved_correlation_id,
        }
        
        try:
            result = self.publisher.publish_event(
                event_type=event_type,
                entity_type="service",
                entity_id=service_id,
                **metadata,
            )
        except KafkaProducerError as exc:
            logger.error("Service event delivery failed after commit: %s", exc, extra={"event_type": event_type, "service_id": service_id})
            self._save_outbox(event_type, "service", service_id, metadata, str(exc))
            return {"status": "delivery_failed", "event_type": event_type, "entity_id": str(service_id)}
        
        logger.info(
            f"Service event published: {event_type}",
            extra={
                "event_type": event_type,
                "entity_type": "service",
                "service_id": service_id,
                "correlation_id": resolved_correlation_id,
                "request_id": resolved_request_id,
            }
        )
        
        return result

    def publish_resource_event(self, event_type: str, *, entity_type: str, entity_id: int, **metadata: object) -> dict[str, object]:
        try:
            return self.publisher.publish_event(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                **metadata,
            )
        except KafkaProducerError as exc:
            logger.error("Resource event delivery failed after commit: %s", exc, extra={"event_type": event_type, "entity_type": entity_type, "entity_id": entity_id})
            self._save_outbox(event_type, entity_type, entity_id, metadata, str(exc))
            return {"status": "delivery_failed", "event_type": event_type, "entity_id": str(entity_id)}

    def publish_billing_event(self, event_type: str, *, billing_id: int, appointment_id: int, amount: float, status: str) -> dict[str, object]:
        return self.publish_resource_event(
            event_type,
            entity_type="billing",
            entity_id=billing_id,
            billing_id=billing_id,
            appointment_id=appointment_id,
            amount=amount,
            status=status,
        )
