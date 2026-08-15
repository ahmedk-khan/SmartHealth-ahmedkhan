from __future__ import annotations

from app.integrations.kafka_client import KafkaEventPublisher


class HealthcareEventService:
    def __init__(self, publisher: KafkaEventPublisher | None = None) -> None:
        self.publisher = publisher or KafkaEventPublisher()

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
    ) -> dict[str, object]:
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
            "request_id": request_id,
            "correlation_id": correlation_id,
            "workflow_id": workflow_id,
        }
        return self.publisher.publish_event(
            event_type=event_type,
            entity_type="appointment",
            entity_id=appointment_id,
            **metadata,
        )

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
        metadata = {
            "service_id": service_id,
            "department_id": department_id,
            "status": status,
            "request_id": request_id,
            "correlation_id": correlation_id,
        }
        return self.publisher.publish_event(
            event_type=event_type,
            entity_type="service",
            entity_id=service_id,
            **metadata,
        )
