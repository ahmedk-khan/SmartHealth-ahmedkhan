"""Central Kafka worker configuration; no publishing or consumer logic."""

from dataclasses import dataclass

from app.core.settings import settings


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str = settings.kafka_bootstrap_servers
    topic_prefix: str = settings.kafka_topic_prefix
    consumer_group: str = settings.kafka_consumer_group
    enabled: bool = settings.kafka_enabled

    def topic(self, event_type: str) -> str:
        normalized = event_type.strip().lower().replace(" ", ".")
        return f"{self.topic_prefix}.{normalized}" if self.topic_prefix else normalized


kafka_config = KafkaConfig()
