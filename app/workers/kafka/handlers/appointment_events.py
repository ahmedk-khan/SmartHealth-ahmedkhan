"""Appointment event handler facade for the analytics consumer."""

from typing import Any

from app.workers.kafka.consumers.analytics_consumer import AnalyticsConsumer


def handle_appointment_event(payload: dict[str, Any], topic: str) -> None:
    """Delegate an appointment event to the existing analytics consumer."""
    AnalyticsConsumer().process_message(payload, topic)
