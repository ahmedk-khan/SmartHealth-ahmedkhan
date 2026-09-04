"""Public Kafka worker API."""

from app.workers.kafka.client import KafkaClient, close_kafka_client, get_kafka_client
from app.workers.kafka.consumer import AnalyticsConsumer, ConsumerConfigError
from app.workers.kafka.exceptions import (
    KafkaConfigError,
    KafkaConnectionError,
    KafkaConsumerError,
    KafkaError,
    KafkaPublisherError,
    KafkaSerializationError,
)
from app.workers.kafka.producer import EventPublisher, KafkaProducer
from app.workers.kafka.serializers import EventEnvelopeV1, JsonSerializer

__all__ = [
    "AnalyticsConsumer",
    "ConsumerConfigError",
    "EventPublisher",
    "KafkaProducer",
    "KafkaClient",
    "get_kafka_client",
    "close_kafka_client",
    "KafkaError",
    "KafkaConfigError",
    "KafkaConnectionError",
    "KafkaConsumerError",
    "KafkaPublisherError",
    "KafkaSerializationError",
    "EventEnvelopeV1",
    "JsonSerializer",
]
