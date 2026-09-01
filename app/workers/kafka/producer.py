"""Thin Kafka publishing adapter.

Business services should publish through the outbox; this module delegates to
the existing PHI-safe publisher and contains no domain decisions.
"""

from typing import Any

from app.integrations.kafka_client import KafkaEventPublisher


class KafkaProducer:
    def __init__(self, publisher: KafkaEventPublisher | None = None) -> None:
        self.publisher = publisher or KafkaEventPublisher()

    async def publish(self, event_type: str, entity_type: str, entity_id: str | int, **metadata: Any) -> dict[str, Any]:
        return await self.publisher.publish_event_async(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            **metadata,
        )
