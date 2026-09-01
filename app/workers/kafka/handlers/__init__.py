"""One handler module per Kafka event family."""

from app.workers.kafka.handlers.appointment_events import handle_appointment_event

__all__ = ["handle_appointment_event"]
