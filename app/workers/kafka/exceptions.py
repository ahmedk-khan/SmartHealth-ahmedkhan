"""Kafka exception types used by the app."""


class KafkaError(Exception):
    """Base exception for Kafka-related errors."""


class KafkaConfigError(KafkaError):
    """Raised when Kafka configuration is invalid or incomplete."""


class KafkaPublisherError(KafkaError):
    """Raised when event publishing to Kafka fails."""


class KafkaConsumerError(KafkaError):
    """Raised when consuming events from Kafka fails."""


class KafkaSerializationError(KafkaError):
    """Raised when event serialization/deserialization fails."""


class KafkaConnectionError(KafkaError):
    """Raised when connecting to Kafka broker fails."""


__all__ = [
    "KafkaError",
    "KafkaConfigError",
    "KafkaPublisherError",
    "KafkaConsumerError",
    "KafkaSerializationError",
    "KafkaConnectionError",
]
