"""Kafka serializer layer."""

import json
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.workers.kafka.exceptions import KafkaSerializationError

logger = logging.getLogger(__name__)


class EventEnvelopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    occurred_at: datetime
    source: str
    schema_version: int = Field(default=1, ge=1)
    entity_type: str
    entity_id: str
    data: dict[str, object] = Field(default_factory=dict)


class JsonSerializer:
    def __init__(self, schema_registry=None):
        self.schema_registry = schema_registry

    def serialize(self, event: dict[str, Any]) -> bytes:
        try:
            json_str = json.dumps(event, default=str)
            return json_str.encode("utf-8")
        except (TypeError, ValueError) as e:
            raise KafkaSerializationError(f"Failed to serialize event: {e}") from e

    def deserialize(self, data: bytes) -> dict[str, Any]:
        try:
            json_str = data.decode("utf-8") if isinstance(data, bytes) else data
            event = json.loads(json_str)
            return event if isinstance(event, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise KafkaSerializationError(f"Failed to deserialize event: {e}") from e

    def validate(self, event: dict[str, Any]) -> bool:
        required_fields = {"event_type", "entity_type", "entity_id"}
        return all(field in event for field in required_fields)


__all__ = ["EventEnvelopeV1", "JsonSerializer"]
