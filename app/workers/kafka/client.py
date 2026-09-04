

import logging
from typing import Any, Optional

try:
    from kafka import KafkaProducer, KafkaConsumer
    from kafka.errors import KafkaError as KafkaLibError
except ImportError:  # pragma: no cover
    KafkaProducer = None
    KafkaConsumer = None
    KafkaLibError = None

from app.workers.kafka.config import kafka_config
from app.workers.kafka.exceptions import KafkaConnectionError, KafkaConfigError

logger = logging.getLogger(__name__)


class KafkaClient:
    def __init__(self, config=None):
        self.config = config or kafka_config
        self._producer: Optional[Any] = None
        self._consumer: Optional[Any] = None
        self._is_enabled = self.config.enabled

    def get_producer(self) -> Optional[Any]:
        if not self._is_enabled:
            logger.warning("Kafka is disabled; producer unavailable")
            return None

        if self._producer is not None:
            return self._producer

        if KafkaProducer is None:
            raise KafkaConfigError("kafka-python is not installed; install with: pip install kafka-python")

        try:
            self._producer = KafkaProducer(
                bootstrap_servers=self.config.bootstrap_servers.split(","),
                value_serializer=lambda v: v.encode("utf-8") if isinstance(v, str) else v,
                acks="all",
                retries=3,
                max_in_flight_requests_per_connection=1,
            )
            logger.info(f"Kafka producer initialized: {self.config.bootstrap_servers}")
            return self._producer
        except KafkaLibError as e:
            raise KafkaConnectionError(f"Failed to connect Kafka producer: {e}") from e

    def get_consumer(self, topics: list[str], group_id: Optional[str] = None) -> Optional[Any]:
        if not self._is_enabled:
            logger.warning("Kafka is disabled; consumer unavailable")
            return None

        if KafkaConsumer is None:
            raise KafkaConfigError("kafka-python is not installed; install with: pip install kafka-python")

        try:
            group = group_id or self.config.consumer_group
            self._consumer = KafkaConsumer(
                *topics,
                bootstrap_servers=self.config.bootstrap_servers.split(","),
                group_id=group,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda m: m.decode("utf-8") if m else None,
            )
            logger.info(f"Kafka consumer initialized: group={group}, topics={topics}")
            return self._consumer
        except KafkaLibError as e:
            raise KafkaConnectionError(f"Failed to connect Kafka consumer: {e}") from e

    def close(self):
        if self._producer:
            self._producer.close()
            self._producer = None
        if self._consumer:
            self._consumer.close()
            self._consumer = None
        logger.info("Kafka client connections closed")

    def is_healthy(self) -> bool:
        if not self._is_enabled:
            return True
        try:
            producer = self.get_producer()
            if producer:
                producer.partitions_for("__test__")
                return True
        except Exception as e:
            logger.error(f"Kafka health check failed: {e}")
            return False
        return False


_client: Optional[KafkaClient] = None


def get_kafka_client(config=None) -> KafkaClient:
    global _client
    if _client is None:
        _client = KafkaClient(config)
    return _client


def close_kafka_client():
    global _client
    if _client:
        _client.close()
        _client = None


__all__ = ["KafkaClient", "get_kafka_client", "close_kafka_client"]
