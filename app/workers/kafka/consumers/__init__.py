"""Kafka consumers; consumers delegate event handling to application services."""

from app.workers.kafka.consumers.analytics_consumer import AnalyticsConsumer, ConsumerConfigError

__all__ = ["AnalyticsConsumer", "ConsumerConfigError"]
